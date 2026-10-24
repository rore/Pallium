"""Actual v0.22.4 route/queue probes; run only in the existing offline Linux boundary."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from types import ModuleType
from unittest.mock import patch
import uuid

if __package__:
    from .hermes_linux_guard import require_contained_paths, require_linux_qualification
else:
    from hermes_linux_guard import require_contained_paths, require_linux_qualification


REVISION = "4d04303818b61bf3aa09278af48356315515965b"
SOURCE_BLOBS = {
    "hermes_cli/plugins_injection.py": "ed6378f5020b03625c244a332e131a8468e43e4f",
    "tui_gateway/plugin_inject.py": "66dae32a526d0786ebde4189331ae1314bceaab4",
    "gateway/run_plugin_injection.py": "cc3e3d381d62f3b27a13399b77dac01fa051386f",
    "gateway/session_local_recovery.py": "0661918b2156e6a6f8a8d17e92dbdec20a413eb2",
    "gateway/session_authority.py": "fe9edf5be5c4d303573c9073f8012203bade8560",
    "tui_gateway/session_auto_continue.py": "ba20b94d41b8ed094923d4084c189220b1278ee0",
    "hermes_cli/plugins.py": "0e5f3b1601fc3481e96840a0e65442b00822538c",
    "hermes_state_runtime.py": "516e3ea46152226e320dc0b6236e6af0b2a00ccb",
}
PLUGIN = "pallium-hermes-relay"
MARKER = "ROUTE_PROBE_שלום_🌍"


async def probe(source: Path, work: Path, case: str) -> dict:
    boundary = require_linux_qualification()
    require_contained_paths(source, work, Path(__file__), Path(sys.executable))
    for name, expected in SOURCE_BLOBS.items():
        data = (source / name).read_bytes()
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == expected, name
    sys.path.insert(0, str(source))
    work.mkdir(mode=0o700)
    home = work / ".hermes"
    alpha = home / "profiles" / "alpha"
    alpha.mkdir(parents=True, mode=0o700)
    (alpha / "config.yaml").write_text(json.dumps({"plugins": {"entries": {
        PLUGIN: {"allow_gateway_injection": True}}}}), encoding="utf-8")

    with ExitStack() as patches:
        patches.enter_context(patch.object(Path, "home", lambda: work))
        patches.enter_context(patch.dict(os.environ, {"HERMES_HOME": str(home)}))
        from gateway import run
        from gateway.config import GatewayConfig
        from gateway.run import _profile_runtime_scope
        from gateway.run_runtime import initialize_gateway_runtime
        from gateway.runtime_ownership import process_ownership
        from gateway.session_contract import Principal
        from gateway.session_local import create_local_session
        from gateway.session_local_recovery import restore_local_session
        from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
        from hermes_state_runtime import RuntimeStoreError, admit_session_input, list_session_admissions

        patches.enter_context(patch.object(run, "_load_gateway_config", lambda: {
            "platform_toolsets": {"cli": []}}))
        homes = [("default", home), ("alpha", alpha)]
        process_ownership.reserve([path for _, path in homes])
        runner = None
        logs = []

        class Capture(logging.Handler):
            def emit(self, record):
                logs.append(record.getMessage())

        handler = Capture()
        logging.getLogger().addHandler(handler)
        try:
            config = GatewayConfig()
            config.multiplex_profiles = True
            config._runtime_profile_homes = tuple(homes)
            runner = run.GatewayRunner(config)
            await initialize_gateway_runtime(runner)
            authority = runner.session_authorities.for_home(alpha)
            actor = Principal("owner", authority.profile_id,
                              frozenset({"session:create", "session:read", "session:control"}), "socket")
            with _profile_runtime_scope(alpha, {}):
                ref = create_local_session(authority, actor, {
                    "request_id": "route-probe", "source": "gui", "cwd": str(work),
                    "model": "frozen", "toolsets": []})
                assert restore_local_session(authority, ref.session_id) == ref
            live = authority.sessions[ref.session_id]
            route = live.route
            store = runner.session_store
            manager = PluginManager(scope_key=str(alpha))
            context = PluginContext(PluginManifest(name=PLUGIN), manager)
            assert context._gateway_injection_allowed()
            result = {"case": case, "revision": REVISION, "source_blobs": SOURCE_BLOBS,
                      "healthy_restore": True, "session_id": ref.session_id,
                      "qualification_run": boundary["run_id"]}

            with _profile_runtime_scope(alpha, {}):
                if case == "live_restore":
                    with store._lock:
                        store._entries.pop(route)
                    for index in range(2):
                        admit_session_input(authority.db, epoch=authority.epoch, principal_id=actor.subject,
                                            session_id=ref.session_id, request_id=f"queued-{index}",
                                            payload={"input": f"{MARKER}-{index}"})
                        assert await authority._claim_with_retry(ref, live) is None
                        rows = list_session_admissions(authority.db, session_id=ref.session_id)
                        assert len(rows) == index + 1 and all(row["status"] == "queued" for row in rows)
                        assert ref.session_id in authority.sessions and store._entry_locked(route) is None
                    assert sum("paused: admission_conflict" in line for line in logs) == 2
                    result.update(pauses=2, queued=2, admission_conflict=True)

                    # A cold restore heals the absent entry; this is not a process-restart test.
                    authority.sessions.pop(ref.session_id)
                    assert restore_local_session(authority, ref.session_id) == ref
                    assert store._entry_locked(route).session_id == ref.session_id
                    rival = create_local_session(authority, actor, {
                        "request_id": "rival", "source": "gui", "cwd": str(work),
                        "model": "frozen", "toolsets": []})
                    admit_session_input(authority.db, epoch=authority.epoch, principal_id=actor.subject,
                                        session_id=rival.session_id, request_id="rival-input",
                                        payload={"input": "rival remains owned"})
                    with store._lock:
                        store._entries[route].session_id = rival.session_id
                    try:
                        restore_local_session(authority, ref.session_id)
                    except RuntimeStoreError as error:
                        assert error.reason == "admission_conflict"
                    else:
                        raise AssertionError("restore took over a non-stray rival")
                    assert store._entry_locked(route).session_id == rival.session_id
                    result.update(cold_restore=True, non_stray_rival_refused=True)

                elif case == "gateway":
                    runner._running = True
                    runner._gateway_loop = asyncio.get_running_loop()
                    assert runner._plugin_session_key_admissible(route, plugin_home=alpha, plugin_id=PLUGIN)
                    with store._lock:
                        store._entries.pop(route)
                    manager.set_gateway_message_injector(runner, runner._schedule_plugin_message_injection)
                    assert context.inject_message(MARKER, session_key=route) is True
                    tasks = tuple(runner._background_tasks)
                    assert len(tasks) == 1
                    assert await asyncio.wait_for(asyncio.gather(*tasks), 3) == [False]
                    await asyncio.sleep(0)  # run the actual scheduler's completion/log callbacks
                    assert list_session_admissions(authority.db, session_id=ref.session_id) == []
                    assert any("Plugin message injection was not routed" in line for line in logs)
                    assert not any("paused: admission_conflict" in line for line in logs)
                    assert not runner._background_tasks
                    result.update(scheduled=True, dispatched=False, queued=0, not_routed=True)

                elif case == "tui":
                    from tui_gateway import plugin_inject, session_auto_continue

                    # Bind the shipped functions as server.py does; busy sessions never start inference.
                    host = ModuleType("contained_tui_host")
                    host.time, host.uuid, host.threading = time, uuid, threading
                    host._sessions_lock = threading.RLock()
                    target = {"session_key": route, "running": True, "history_lock": threading.RLock()}
                    other = {"session_key": "foreign-route", "running": True,
                             "history_lock": threading.RLock()}
                    host._sessions = {"ui-target": target, "ui-other": other}
                    session_auto_continue.register(host)
                    plugin_inject.register(host)
                    manager.set_tui_message_injector(host, host.inject_tui_session_message)

                    def no_gateway(**_kwargs):
                        raise AssertionError("TUI-owned input fell through to the gateway")

                    manager.set_gateway_message_injector(runner, no_gateway)
                    with store._lock:
                        store._entries.pop(route)
                    assert context.inject_message(MARKER, session_key=route) is True
                    assert target["queued_prompt"] == {"text": MARKER, "transport": None}
                    assert not target.get("queued_prompts") and "queued_prompt" not in other
                    assert target["running"] is True and store._entry_locked(route) is None
                    assert list_session_admissions(authority.db, session_id=ref.session_id) == []
                    result.update(tui_queue=True, gateway_called=False, exact_session=True, queued=1)
                else:
                    raise AssertionError(case)

            # Refuse a mixed editable-install source tree masquerading as this released source.
            roots = {path.stem for path in source.glob("*.py")} | {
                path.name for path in source.iterdir()
                if path.is_dir() and any(path.rglob("*.py"))}
            imported, mixed = [], []
            for name, module in tuple(sys.modules.items()):
                if name.split(".")[0] not in roots:
                    continue
                path = getattr(module, "__file__", None)
                if path:
                    if not Path(path).resolve().is_relative_to(source):
                        mixed.append((name, path))
                    imported.append(name)
                else:
                    for location in getattr(module, "__path__", ()):
                        if not Path(location).resolve().is_relative_to(source):
                            mixed.append((name, location))
            assert not mixed, mixed
            required = {"gateway.run", "gateway.session_authority", "gateway.session_local_recovery",
                        "hermes_cli.plugins", "hermes_state_runtime"}
            if case in {"tui", "gateway"}:
                required.add("hermes_cli.plugins_injection")
            if case == "tui":
                required.update({"tui_gateway.plugin_inject", "tui_gateway.session_auto_continue"})
            assert required <= set(imported), required - set(imported)
            result["actual_source_modules"] = len(imported)
        finally:
            logging.getLogger().removeHandler(handler)
            if runner is not None:
                for task in tuple(runner._background_tasks):
                    assert task.done(), "probe left an active gateway task"
                for owner in getattr(runner, "session_authorities", ()):
                    owner.db.close()
            for _, path in homes:
                process_ownership.release(path)
        result["cleanup"] = "closed databases and released profile ownership"
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--case", choices=("live_restore", "gateway", "tui"), required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(probe(args.source.resolve(), args.work.resolve(), args.case)),
                     ensure_ascii=True), flush=True)
