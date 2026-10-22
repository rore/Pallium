"""Real Hermes public hooks/tools to native stdio MCP and HTTP; no frontend/model loop."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import contextvars
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if __package__:
    from .hermes_linux_guard import require_contained_paths, require_linux_qualification
    from .hermes_route_probe import REVISION, SOURCE_BLOBS
else:
    from hermes_linux_guard import require_contained_paths, require_linux_qualification
    from hermes_route_probe import REVISION, SOURCE_BLOBS


PLUGIN = "pallium-hermes-relay"
PROJECTS = {name: "git:example.test/qualification/" + name for name in ("a", "b", "c")}


def verify_manifest(root: Path, manifest: Path, *, git_blobs: bool) -> dict:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data.get("files"), "empty content manifest"
    if git_blobs:
        assert data.get("revision") == REVISION
        assert all(data["files"].get(name) == value for name, value in SOURCE_BLOBS.items())
    else:
        assert data.get("schema") == "pallium-hermes-scope-artifact/v1"
        assert isinstance(data.get("revision"), str) and len(data["revision"]) == 40
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        assert actual == set(data["files"]), "artifact inventory differs from complete manifest"
        assert {"integrations/hermes/__init__.py", "integrations/hermes/scope.py",
                "integrations/hermes/turn_capture.py", "app/mcp/hermes.py", "core/relay.py",
                "storage/sqlite_relay.py", "tests/fixtures/hermes_scope_probe.py",
                "tests/test_hermes_native_scope_e2e.py"} <= set(data["files"])
    for name, expected in data["files"].items():
        path = root / name
        assert not Path(name).is_absolute() and path.resolve().is_relative_to(root.resolve()), name
        assert not path.is_symlink() and path.is_file(), name
        raw = path.read_bytes()
        digest = (hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                  if git_blobs else hashlib.sha256(raw).hexdigest())
        assert digest == expected, name
    return {"revision": data["revision"], "files": len(data["files"]),
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}


def isolated_env(work: Path, inherited: dict[str, str]) -> dict[str, str]:
    """Create every writable application root before either application's import."""
    env = {key: inherited[key] for key in (
        "PALLIUM_LINUX_QUALIFICATION_ROOT", "PALLIUM_LINUX_QUALIFICATION_MANIFEST") if key in inherited}
    roots = {name: work / name.lower() for name in (
        "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TMPDIR", "TEMP", "TMP",
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "HERMES_HOME", "PALLIUM_HOME")}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    env.update({key: str(value) for key, value in roots.items()})
    env.update(PATH="/qualification/tools/bin:/usr/local/bin:/usr/bin:/bin", LANG="C.UTF-8",
               LC_ALL="C.UTF-8", PYTHONDONTWRITEBYTECODE="1", GIT_NO_LAZY_FETCH="1",
               GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
    return env


def install_guard(work: Path, repo: Path, sdk1: Path) -> list:
    """Namespace blocks egress; audit further restricts writes and child commands."""
    denied = []
    def record(event, detail=None):
        entry = {"event": event, "detail": str(detail)}
        denied.append(entry)
        with (work / "guard-denials.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    def require(condition, event, detail=None):
        if not condition:
            record(event, detail)
            raise PermissionError("qualification boundary refused " + event)
    def audit(event, args):
        if event == "open":
            path, _mode, flags = args
            if isinstance(path, int):
                return
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                require(Path(path).resolve().is_relative_to(work), event, path)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime", "os.truncate"}:
            path = args[0]
            if isinstance(path, int):
                try:
                    path = Path(f"/proc/self/fd/{path}").resolve(strict=True)
                except (OSError, RuntimeError, ValueError):
                    require(False, event, args[0])
            require(Path(path).resolve().is_relative_to(work), event, args[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            require(all(Path(p).resolve().is_relative_to(work) for p in args[:2]), event)
        elif event in {"socket.connect", "socket.bind"}:
            address = args[1]
            require(isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
                    or isinstance(address, str) and Path(address).resolve().is_relative_to(work), event, address)
        elif event == "subprocess.Popen":
            command, cwd = args[1], args[2]
            require(isinstance(command, (list, tuple)) and command, event, "shell child")
            executable = Path(command[0])
            local_git = (executable.name == "git" and len(command) > 1
                         and command[1] in {"init", "config", "commit", "remote", "checkout", "rev-parse", "describe", "status", "rev-list"})
            mcp = (executable == sdk1 and command[1:4] == ["-m", "app.mcp.hermes", "--base-url"]
                   and Path(cwd).resolve() == repo)
            if not (local_git or mcp):
                record(event, executable.name)
                raise PermissionError("unreviewed qualification child")
            if local_git:
                require(cwd and (Path(cwd).resolve().is_relative_to(work)
                                 or command[1] in {"rev-parse", "describe", "status", "rev-list"}), event, cwd)
        elif event in {"os.system", "os.fork", "os.posix_spawn", "socket.sendto"}:
            record(event)
            raise PermissionError("unreviewed qualification operation")
    sys.addaudithook(audit)
    return denied


def http(base: str, path: str, query=None):
    url = base + path + ("?" + urlencode(query) if query else "")
    with urlopen(Request(url), timeout=10) as response:
        assert response.status == 200
        return json.load(response)


def service(args):
    boundary = require_linux_qualification()
    require_contained_paths(args.work, args.repo, Path(sys.executable))
    os.chdir(args.work)
    sys.path.insert(0, str(args.repo))
    denied = install_guard(args.work, args.repo, args.sdk1)
    from app.config import AppConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    import uvicorn
    config = AppConfig(sqlite_url="sqlite:///" + str(args.work / "history.db"),
                       relay_sqlite_url="sqlite:///" + str(args.work / "relay.db"),
                       vector_index=VectorIndexConfig(enabled=False))
    assert not any(package.enabled for package in config.semantic_packages.values())
    assert not config.llm_providers
    app = create_app(config)
    (args.work / "service-receipt.json").write_text(json.dumps({
        "qualification_run": boundary["run_id"], "semantic_packages_enabled": [],
        "vector_index_enabled": False, "python": sys.executable,
        "mcp_version": importlib.metadata.version("mcp")}), encoding="utf-8")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    assert not denied, denied


def process_identity(pid):
    """PID reuse cannot grant authority over a replacement process."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
        return {"pid": pid, "start_time": int(fields[19]), "process_group": int(fields[2])}
    except (FileNotFoundError, ProcessLookupError):
        return None


def identity_key(identity):
    return str(identity["pid"]) + ":" + str(identity["start_time"])


def matches_process(record):
    current = process_identity(record["pid"])
    return current is not None and identity_key(current) == identity_key(record)


def capture_owned(records, roots=()):
    """Follow every spawning TID, including the bridge's background thread."""
    pending, visited = [*roots, *records.values()], set()
    while pending:
        parent = pending.pop()
        key = identity_key(parent)
        if key in visited or not matches_process(parent):
            continue
        visited.add(key)
        if key in records:
            records[key] = process_identity(parent["pid"]) or parent
        for path in Path(f"/proc/{parent['pid']}/task").glob("*/children"):
            try:
                children = path.read_text().split()
            except (FileNotFoundError, ProcessLookupError):
                continue
            for value in children:
                child = process_identity(int(value))
                if child is not None:
                    records[identity_key(child)] = child
                    pending.append(child)


def save_owned(path, records, owner=None):
    payload = json.dumps({"schema": "pallium-owned-processes/v1", "owner": owner,
                          "processes": sorted(records.values(), key=lambda row: (row["pid"], row["start_time"]))}, indent=2)
    if path.exists() and path.read_text() == payload:
        return
    temporary = path.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def remaining_owned(records):
    return [record for record in records.values() if matches_process(record)]


def signal_owned(record, sig):
    """A pidfd targets this incarnation even if its numeric PID is recycled."""
    if not matches_process(record):
        return False
    try:
        descriptor = os.pidfd_open(record["pid"])
    except ProcessLookupError:
        return False
    try:
        if not matches_process(record):
            return False
        signal.pidfd_send_signal(descriptor, sig)
        return True
    except ProcessLookupError:
        return False
    finally:
        os.close(descriptor)


def host(args):
    boundary = require_linux_qualification()
    require_contained_paths(args.source, args.work, args.repo, args.sdk1, Path(sys.executable))
    source_receipt = verify_manifest(args.source, args.source_manifest, git_blobs=True)
    artifact_receipt = verify_manifest(args.repo, args.artifact_manifest, git_blobs=False)
    assert not (args.source / ".env").exists()
    os.chdir(args.work)
    sys.path.insert(0, str(args.source))
    home = Path(os.environ["HERMES_HOME"])
    plugin = home / "plugins" / PLUGIN
    shutil.copytree(args.repo / "integrations" / "hermes", plugin)
    bundled = args.work / "empty-bundled-plugins"
    bundled.mkdir()
    os.environ["HERMES_BUNDLED_PLUGINS"] = str(bundled)
    settings = {"service_url": args.base, "scope_mode": "cwd", "memory_enabled": False,
                "mcp_python": str(args.sdk1), "mcp_repo": str(args.repo), "visibility": "private"}
    (home / "config.yaml").write_text(json.dumps({"plugins": {"enabled": [PLUGIN], "entries": {
        PLUGIN: {"allow_gateway_injection": True, "settings": settings}}}}), encoding="utf-8")
    roots = {}
    for name in PROJECTS:
        root = args.work / ("project-" + name)
        root.mkdir()
        for command in (["init", "-q", "-b", "main"], ["config", "user.name", "actor-" + name],
                        ["config", "user.email", name + "@example.test"],
                        ["-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "initial"],
                        ["remote", "add", "origin", "https://example.test/qualification/" + name + ".git"],
                        ["checkout", "-q", "-b", "feat/native-" + name]):
            subprocess.run(["git", *command], cwd=root, check=True, capture_output=True,
                           text=True, encoding="utf-8", timeout=5)
        roots[name] = root
    denied = install_guard(args.work, args.repo, args.sdk1)
    from gateway.session_context import set_session_vars, clear_session_vars
    from hermes_cli.plugins import get_plugin_manager
    from hermes_cli.middleware import run_tool_execution_middleware
    from tools.registry import registry
    manager = get_plugin_manager()
    owner = process_identity(os.getpid())
    owned, owned_lock = {}, threading.RLock()
    def checkpoint():
        with owned_lock:
            capture_owned(owned, [owner])
            save_owned(args.work / "owned-processes.json", owned, owner)
    checkpoint()
    receipt = {"qualification_run": boundary["run_id"], "source": source_receipt,
               "artifact": artifact_receipt, "mcp_version": importlib.metadata.version("mcp"),
               "claim": "native public hooks/tools to stdio MCP and HTTP; no frontend or wake admission",
               "checks": [], "tools": [], "http": []}

    @contextmanager
    def session(name, session_id, surface="desktop", cwd=None):
        tokens = set_session_vars(platform=surface, session_id=session_id, session_key=session_id,
                                  cwd=str(roots[name] if cwd is None else cwd))
        try:
            yield
        finally:
            clear_session_vars(tokens)

    def tool(name, arguments, sid, turn, *, error=False):
        raw = run_tool_execution_middleware(name, arguments,
            lambda actual: registry.dispatch(name, actual, scope=manager.scope_key, session_id=sid),
            session_id=sid, turn_id=turn)
        result = json.loads(raw) if isinstance(raw, str) else raw
        checkpoint()
        assert isinstance(result, dict), result
        assert ("error" in result) is error, result
        receipt["tools"].append({"name": name, "session": sid, "turn": turn, "result": result})
        return result

    def rows(project, sid):
        result = http(args.base, "/relay/sessions", {"runtime": "hermes", "session_ref": sid,
                      "container_ref": PROJECTS[project], "include_inactive": "true"})
        receipt["http"].append({"project": project, "session": sid, "result": result})
        return result

    def pre(sid, turn, message):
        result = manager.invoke_hook("pre_llm_call", session_id=sid, turn_id=turn,
            user_message=message, conversation_history=[{"role": "user", "content": message}])
        assert any(isinstance(row, dict) and "request_source_item_id" in row.get("context", "")
                   for row in result), result
        return result

    def complete(sid, turn, message):
        answer = "completed 漢字 " + turn
        history = [{"role": "user", "content": message, "message_uid": "user-" + turn},
                   {"role": "assistant", "content": answer, "message_uid": "answer-" + turn}]
        for _ in range(2):
            manager.invoke_hook("post_llm_call", session_id=sid, turn_id=turn,
                user_message=message, assistant_response=answer, conversation_history=history)
        manager.invoke_hook("on_session_end", session_id=sid, turn_id=turn)

    try:
        manager.discover_and_load()
        checkpoint()
        plugins = manager.list_plugins()
        loaded = next(row for row in plugins if row["name"] == PLUGIN)
        assert loaded["enabled"] and not loaded["error"] and loaded["tools"] >= 15, loaded
        assert loaded["hooks"] >= 5 and loaded["middleware"] >= 2, loaded
        receipt["registration"] = loaded
        assert importlib.metadata.version("mcp").startswith("2."), "host requires existing SDK2"
        barrier = threading.Barrier(2)
        def initial(name, surface):
            sid, turn = "native-" + name, "initial-" + name
            marker = "scope-native-" + name + " café שלום 🌍"
            with session(name, sid, surface):
                barrier.wait(timeout=10)
                pre(sid, turn, marker)
                address = tool("pallium_relay_address", {}, sid, turn)
                assert address["session_ref"] == sid
                complete(sid, turn, marker)
                tool("pallium_relay_address", {}, sid, turn, error=True)
                assert rows(name, sid)[0]["state"] == "recent"
            return {"name": name, "surface": surface, "marker": marker, "address": address}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(contextvars.copy_context().run, initial, name, surface)
                       for name, surface in (("a", "desktop"), ("b", "tui"))]
            initial_results = [future.result(timeout=90) for future in futures]
        receipt["initial_contexts"] = initial_results
        receipt["checks"].append("concurrent Desktop/TUI capture and ended-turn refusal")
        with session("a", "reader-a"):
            pre("reader-a", "search-a", "search earlier captured session")
            found = tool("pallium_search_history", {"query": initial_results[0]["marker"], "role": "user", "limit": 10}, "reader-a", "search-a")
            assert len(found["results"]) == 1, found
            assert found["lookup_event_id"]
            expanded = tool("pallium_expand_source", {"source_item_id": found["results"][0]["source_item_id"],
                "parent_lookup_id": found["lookup_event_id"], "before": 1, "after": 1}, "reader-a", "search-a")
            assert initial_results[0]["marker"] in json.dumps(expanded, ensure_ascii=False)
            assert "completed 漢字 initial-a" in json.dumps(expanded, ensure_ascii=False)
            raw = http(args.base, "/source/" + found["results"][0]["source_item_id"] + "/context",
                       {"container_ref": PROJECTS["a"], "query_actor_ref": "actor-a",
                        "query_visibility": "private", "before": 1, "after": 1})
            assert sum(row["content"] == initial_results[0]["marker"] for row in raw["items"]) == 1
            receipt["http"].append({"history_context": raw})
        with session("b", "reader-b", "tui"):
            pre("reader-b", "search-b", "search unrelated project")
            absent = tool("pallium_search_history", {"query": initial_results[0]["marker"], "limit": 10}, "reader-b", "search-b")
            assert absent["results"] == [], absent
        receipt["checks"].append("real History search/expand, completion dedup and project isolation")
        # End each old turn before following a three-project chain.
        manager.invoke_hook("on_session_end", session_id="reader-a", turn_id="search-a")
        for index, name in enumerate(("b", "c", "a")):
            with session(name, "native-a"):
                turn = "transition-" + str(index)
                pre("native-a", turn, "ordinary transition " + turn)
                assert tool("pallium_relay_address", {}, "native-a", turn)["session_ref"] == "native-a"
                assert rows(name, "native-a")[0]["state"] == "recent"
                complete("native-a", turn, "ordinary transition " + turn)
        receipt["checks"].append("completed A to B to C to A project chain")
        transient = args.work / "transient"
        transient.mkdir()
        with session("a", "native-a", cwd=transient):
            pre("native-a", "transient", "valid transient directory retains Git pin")
            assert rows("a", "native-a")[0]["state"] == "recent"
            tool("pallium_relay_address", {}, "native-a", "transient")
            complete("native-a", "transient", "valid transient directory retains Git pin")
        for index, invalid in enumerate(("", ".", str(args.work / "missing"))):
            with session("a", "native-a", cwd=invalid):
                turn = "invalid-" + str(index)
                result = manager.invoke_hook("pre_llm_call", session_id="native-a", turn_id=turn,
                                             user_message="invalid cwd must confer no authority")
                assert not result, result
                tool("pallium_relay_address", {}, "native-a", turn, error=True)
        receipt["checks"].append("transient Git pin and empty/relative/missing cwd refusal")
        checkpoint()
        manager.unload()
        manager.discover_and_load(force=True)
        checkpoint()
        with session("a", "native-a"):
            pre("native-a", "after-reload", "new ordinary turn after actual manager reload")
            active = rows("a", "native-a")[0]
            tool("pallium_relay_address", {}, "native-a", "after-reload")
            manager.invoke_hook("on_session_finalize", session_id="native-a")
            assert rows("a", "native-a")[0]["state"] == "closed"
            tool("pallium_relay_address", {}, "native-a", "after-reload", error=True)
            pre("native-a", "resumed", "new ordinary turn after finalize")
            resumed = rows("a", "native-a")[0]
            assert resumed["state"] == "recent" and resumed["scope_generation"] > active["scope_generation"]
            manager.invoke_hook("on_session_delete", session_id="native-a")
            assert rows("a", "native-a")[0]["state"] == "closed"
        receipt["checks"].append("actual unload/reload, guarded finalize/delete and fresh incarnation")
        source_roots = {p.stem for p in args.source.glob("*.py")} | {
            p.name for p in args.source.iterdir() if p.is_dir() and (p / "__init__.py").is_file()}
        imported = {}
        for name, module in tuple(sys.modules.items()):
            if name.split(".")[0] not in source_roots:
                continue
            path = getattr(module, "__file__", None)
            if path:
                resolved = Path(path).resolve()
                assert resolved.is_relative_to(args.source), ("mixed host source", name, path)
                imported[name] = hashlib.sha256(resolved.read_bytes()).hexdigest()
        assert {"hermes_cli.plugins", "hermes_cli.middleware", "gateway.session_context",
                "tools.registry", "agent.runtime_cwd"} <= set(imported)
        receipt["actual_source_modules"] = imported
        assert not denied, denied
        receipt["passed"] = True
    finally:
        checkpoint()
        unload_error = None
        try:
            manager.unload()
        except BaseException as error:
            unload_error = repr(error)
        checkpoint()
        deadline = time.monotonic() + 10
        while remaining_owned(owned) and time.monotonic() < deadline:
            checkpoint()
            time.sleep(0.05)
        remaining = remaining_owned(owned)
        receipt["cleanup"] = {"owned_processes": list(owned.values()), "remaining": remaining,
                              "normal_cleanup": not remaining and unload_error is None,
                              "unload_error": unload_error,
                              "bridge_threads": [t.name for t in threading.enumerate()
                                                 if t.name.startswith("pallium-hermes")]}
        receipt["denied_actions"] = denied
        receipt["passed"] = bool(receipt.get("passed") and not remaining and not unload_error
                                 and not receipt["cleanup"]["bridge_threads"])
        (args.work / "host-receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
        assert not remaining and not unload_error and not receipt["cleanup"]["bridge_threads"], receipt["cleanup"]
    print(json.dumps({"passed": True, "checks": receipt["checks"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("service", "host"), required=True)
    for name in ("work", "repo", "sdk1", "source", "source-manifest", "artifact-manifest"):
        parser.add_argument("--" + name, type=Path, required=name in {"work", "repo", "sdk1"})
    parser.add_argument("--base")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    for name in ("work", "repo", "sdk1", "source", "source_manifest", "artifact_manifest"):
        if getattr(args, name) is not None:
            value = getattr(args, name)
            setattr(args, name, Path(os.path.abspath(value)) if name == "sdk1" else value.resolve())
    (service if args.mode == "service" else host)(args)
