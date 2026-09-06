"""Real caller -> HTTP ingest -> SQLite coverage for structural work refs."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SECRET = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
STRUCTURAL = ["git-branch:fix/alpha", "agent-workflow:alpha"]
CASES = [
    ([], STRUCTURAL, []),
    (
        ["ONE", "TWO", "THREE", "FOUR", "FIVE"],
        STRUCTURAL + ["one", "two", "three"],
        ["one", "two", "three", "four", "five"],
    ),
    (
        ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX"],
        STRUCTURAL + ["one", "two", "three"],
        ["one", "two", "three", "four", "five"],
    ),
    (
        [SECRET, "PROJ 1", "proj_1", "SYNC-2", "", "EXTRA", "LAST"],
        STRUCTURAL + ["proj-1", "sync-2", "extra"],
        ["proj-1", "sync-2", "extra", "last"],
    ),
]


def _load(name: str, path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(path.parent))
    monkeypatch.delitem(sys.modules, "common", raising=False)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _repo_metadata(path: Path) -> Path:
    path.mkdir()
    git = path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/fix/alpha\n", encoding="utf-8")
    tasks = path / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "alpha.md").write_text(
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
        encoding="utf-8",
    )
    return path


def _quiet_common_side_effects(module, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, replacement in (
        ("register_claude_wake", lambda *_a, **_k: None),
        ("get_pending_relay_closes", lambda *_a, **_k: []),
        ("pin_container", lambda *_a, **_k: None),
        ("relay_request", lambda *_a, **_k: None),
        ("acknowledge_relay", lambda *_a, **_k: []),
    ):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, replacement)


def _python_payloads(
    cwd: Path,
    explicit: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict]:
    captured: list[dict] = []
    for host, relative in (
        ("claude", "claude-code/hooks"),
        ("codex", "codex/hooks"),
    ):
        base = Path("integrations") / relative
        prompt = _load(f"{host}_prompt_real", base / "user_prompt_submit.py", monkeypatch)
        prompt_input = {
            "cwd": str(cwd),
            "session_id": f"{host}-user",
            "prompt": "Continue this substantial task",
            "pallium_work_refs": list(explicit),
        }
        monkeypatch.setattr(prompt, "read_hook_input", lambda value=prompt_input: value)
        monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: "git:example.test/repo")
        monkeypatch.setattr(prompt, "derive_actor_ref", lambda: "actor")
        monkeypatch.setattr(prompt, "check_dedup", lambda *_: False)
        _quiet_common_side_effects(prompt, monkeypatch)
        if hasattr(prompt, "emit_context"):
            monkeypatch.setattr(prompt, "emit_context", lambda *_: None)

        def prompt_request(_method, path, body=None, **_kwargs):
            if path == "/item-and-query":
                captured.append(body)
                return {"source_item_id": "request-user", "injectable_blocks": []}
            return None

        monkeypatch.setattr(prompt, "pallium_request", prompt_request)
        with pytest.raises(SystemExit):
            prompt.main()

        stop = _load(f"{host}_stop_real", base / "stop.py", monkeypatch)
        stop_input = {
            "cwd": str(cwd),
            "session_id": f"{host}-stop",
            "transcript_path": "turn.jsonl",
            "pallium_work_refs": list(explicit),
            "stop_hook_active": True,
        }
        monkeypatch.setattr(stop, "read_hook_input", lambda value=stop_input: value)
        monkeypatch.setattr(stop, "resolve_container_ref", lambda *_: "git:example.test/repo")
        monkeypatch.setattr(stop, "derive_actor_ref", lambda: "actor")
        monkeypatch.setattr(
            stop,
            "read_turn",
            lambda _path: SimpleNamespace(
                assistant_text="Completed substantial work.",
                tool_calls=[],
                has_productive_action=False,
            ),
        )
        monkeypatch.setattr(stop, "build_work_trace_metadata", lambda _turn: None)
        monkeypatch.setattr(stop, "_populate_usage_audit_rows", lambda *_: None)
        _quiet_common_side_effects(stop, monkeypatch)

        def stop_request(_method, path, body=None, **_kwargs):
            if path == "/items":
                captured.append(body[0])
            return {}

        monkeypatch.setattr(stop, "pallium_request", stop_request)
        with pytest.raises(SystemExit):
            stop.main()
    return captured


def _opencode_payloads(cwd: Path, explicit: list[str], state_home: Path) -> list[dict]:
    plugin = Path("integrations/opencode/.opencode/plugins/pallium.mjs").resolve().as_uri()
    script = r'''import pluginFactory from "__PLUGIN__";
const calls = [];
global.fetch = async (url, init) => {
  const body = init?.body ? JSON.parse(init.body) : undefined;
  calls.push({url: String(url), body});
  return {ok:true, status:200, text:async()=>JSON.stringify(
    String(url).includes("/items") ? [{source_item_id:"sid"}] :
    String(url).includes("/relay/") ? {deliveries:[]} :
    {source_item_id:"sid", injectable_blocks:[]}
  )};
};
const client = {
  session:{messages:async()=>({data:[{info:{role:"assistant",id:"a1"},parts:[{type:"text",text:"Completed substantial work."}]}]})},
  app:{log(){}}
};
const hooks = await pluginFactory({client, directory:__DIR__});
await hooks["chat.message"](
  {metadata:{pallium_work_refs:__EXPLICIT__}},
  {message:{sessionID:"oc-user"},parts:[{type:"text",text:"Continue this substantial task"}]}
);
await hooks.event({event:{type:"session.idle",properties:{sessionID:"oc-user"}}});
console.log(JSON.stringify(
  calls.filter(call=>call.url.includes("/item-and-query")||call.url.includes("/items")).map(call=>call.body)
));
'''
    script = (
        script.replace("__PLUGIN__", plugin)
        .replace("__DIR__", json.dumps(cwd.as_posix()))
        .replace("__EXPLICIT__", json.dumps(explicit))
    )
    environment = {**os.environ, "USERPROFILE": str(state_home), "HOME": str(state_home)}
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
        env=environment,
        timeout=20,
    )
    return json.loads(result.stdout.strip())


def _opencode_prompt_scope(cwd: Path, state_home: Path) -> dict:
    plugin = Path("integrations/opencode/.opencode/plugins/pallium.mjs").resolve().as_uri()
    script = r'''import pluginFactory from "__PLUGIN__";
const calls = [];
global.fetch = async (url, init) => {
  const body = init?.body ? JSON.parse(init.body) : undefined;
  calls.push({url:String(url), body});
  return {ok:true, status:200, text:async()=>JSON.stringify(
    String(url).includes("/relay/") ? {deliveries:[]} :
    {source_item_id:"scope-source", injectable_blocks:[]}
  )};
};
const client = {session:{messages:async()=>({data:[]})}, app:{log(){}}};
const hooks = await pluginFactory({client, directory:__DIR__});
const output = {
  message:{sessionID:"oc-scope", role:"user"},
  parts:[{type:"text", text:"Continue this substantial task"}],
};
await hooks["chat.message"]({metadata:{pallium_work_refs:["EXPLICIT-REF"]}}, output);
const transformed = {messages:[{info:output.message, parts:output.parts}]};
await hooks["experimental.chat.messages.transform"]({}, transformed);
const system = {system:[]};
await hooks["experimental.chat.system.transform"](
  {message:{sessionID:"oc-scope"}}, system
);
const text = transformed.messages[0].parts[0].text + "\n" + system.system.join("\n");
const refs = [...text.matchAll(/"work_ref":"([^"]+)"/g)].map((match)=>match[1]);
console.log(JSON.stringify({
  payload:calls.find((call)=>call.url.includes("/item-and-query")).body,
  refs,
}));
'''
    script = script.replace("__PLUGIN__", plugin).replace(
        "__DIR__", json.dumps(cwd.as_posix())
    )
    environment = {**os.environ, "USERPROFILE": str(state_home), "HOME": str(state_home)}
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
        env=environment,
        timeout=20,
    )
    return json.loads(result.stdout.strip())


def _ingest(client, payload: dict):
    if isinstance(payload, list):
        payload = payload[0]
    body = dict(payload)
    body.update(use_case="demo_agent_memory", artifact_kind="message", visibility="private")
    if "query_text" in body:
        return client.post("/item-and-query", json=body)
    return client.post("/items", json=[body])


def _stored(client, payload: dict):
    if isinstance(payload, list):
        payload = payload[0]
    return client.app.state.pallium_service._storage.find_source_item(
        payload["source_type"], payload["source_id"]
    )


@pytest.mark.parametrize(
    "explicit,expected,explicit_only",
    CASES,
    ids=("empty", "max", "over-max", "secret-dedupe"),
)
def test_all_real_callers_capture_and_ingest_exact_refs(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit: list[str],
    expected: list[str],
    explicit_only: list[str],
) -> None:
    repo = _repo_metadata(tmp_path / "repo")
    captured = _python_payloads(repo, explicit, monkeypatch)
    captured += _opencode_payloads(repo, explicit, tmp_path / "node-home")
    assert [(item[0] if isinstance(item, list) else item)["role"] for item in captured] == [
        "user", "assistant", "user", "assistant", "user", "assistant"
    ]

    for payload in captured:
        item_payload = payload[0] if isinstance(payload, list) else payload
        response = _ingest(client, payload)
        assert response.status_code == 200, response.text
        item = _stored(client, payload)
        assert item is not None
        # OpenCode has a documented explicit-ref extension on chat.message,
        # but its assistant event has no caller metadata field. On Windows its
        # structural resolver intentionally performs no filesystem access.
        if item_payload["source_type"] == "opencode" and os.name == "nt":
            wanted = explicit_only if item_payload["role"] == "user" else []
        elif item_payload["source_type"] == "opencode" and item_payload["role"] == "assistant":
            wanted = STRUCTURAL
        else:
            wanted = expected
        if wanted:
            assert item.metadata["pallium_work_refs"] == wanted
        else:
            assert "pallium_work_refs" not in item.metadata
        assert SECRET not in json.dumps(item.metadata)


@pytest.mark.parametrize("host,relative", [
    ("claude", "claude-code/hooks"),
    ("codex", "codex/hooks"),
])
def test_python_user_and_assistant_resolver_failure_ingest_explicit_only(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
    relative: str,
) -> None:
    captured = _python_payloads(tmp_path / "missing", CASES[-1][0], monkeypatch)
    selected = [
        payload for payload in captured
        if payload["source_type"] == ("claude-code" if host == "claude" else "codex")
    ]
    assert [payload["role"] for payload in selected] == ["user", "assistant"]
    for payload in selected:
        response = _ingest(client, payload)
        assert response.status_code == 200, response.text
        item = _stored(client, payload)
        assert item is not None
        assert item.metadata["pallium_work_refs"] == ["proj-1", "sync-2", "extra", "last"]


def test_opencode_user_and_assistant_resolver_failure_still_ingest(
    client,
    tmp_path: Path,
) -> None:
    captured = _opencode_payloads(
        tmp_path / "missing",
        CASES[-1][0],
        tmp_path / "node-home",
    )
    assert len(captured) == 2
    for payload in captured:
        item_payload = payload[0] if isinstance(payload, list) else payload
        response = _ingest(client, payload)
        assert response.status_code == 200, response.text
        item = _stored(client, payload)
        assert item is not None
        if item_payload["role"] == "user":
            assert item.metadata["pallium_work_refs"] == [
                "proj-1", "sync-2", "extra", "last"
            ]
        else:
            assert "pallium_work_refs" not in item.metadata


@pytest.mark.parametrize(
    "host,relative",
    (("codex", "codex/hooks"), ("claude", "claude-code/hooks")),
)
def test_python_caller_scope_work_ref_round_trips_into_exact_http_search(
    host: str,
    relative: str,
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo_metadata(tmp_path / "repo")
    prompt = _load(
        f"{host}_scope_e2e",
        Path("integrations") / relative / "user_prompt_submit.py",
        monkeypatch,
    )
    payload = {
        "cwd": str(repo),
        "session_id": "scope-user",
        "prompt": "Continue this substantial task",
        "pallium_work_refs": ["EXPLICIT-REF"],
    }
    original_discover = prompt.discover_work_refs
    ingested: list[dict] = []
    emitted: list[str] = []
    discoveries = 0
    monkeypatch.setattr(prompt, "read_hook_input", lambda: payload)

    def discover(cwd):
        nonlocal discoveries
        discoveries += 1
        return original_discover(cwd)

    monkeypatch.setattr(prompt, "discover_work_refs", discover)
    monkeypatch.setattr(
        prompt, "resolve_container_ref", lambda *_a: "git:example.test/repo"
    )
    monkeypatch.setattr(prompt, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(prompt, "check_dedup", lambda *_a: False)
    monkeypatch.setattr(prompt, "get_pending_relay_closes", lambda *_a: [])
    monkeypatch.setattr(prompt, "relay_request", lambda *_a, **_k: None)
    monkeypatch.setattr(prompt, "pin_container", lambda *_a, **_k: None)
    if hasattr(prompt, "emit_context"):
        monkeypatch.setattr(
            prompt, "emit_context", lambda text, _event: emitted.append(text)
        )

    def request(_method, path, body=None, **_kwargs):
        if path == "/item-and-query":
            ingested.append(body)
            return {"source_item_id": "scope-source", "injectable_blocks": []}
        return None

    monkeypatch.setattr(prompt, "pallium_request", request)
    with pytest.raises(SystemExit):
        prompt.main()

    assert discoveries == 1
    assert len(ingested) == 1
    output = "\n".join(emitted) if emitted else capsys.readouterr().out
    scope_text = next(line for line in output.splitlines() if "Pallium scope" in line)
    scope = json.loads(scope_text.split("— ", 1)[1].split("]", 1)[0])
    assert scope["work_ref"] == "git-branch:fix/alpha"
    assert ingested[0]["metadata"]["pallium_work_refs"] == [
        "git-branch:fix/alpha",
        "agent-workflow:alpha",
        "EXPLICIT-REF",
    ]

    ingest = client.post(
        "/item-and-query",
        json={
            **ingested[0],
            "use_case": "demo_agent_memory",
            "artifact_kind": "message",
            "visibility": "private",
        },
    )
    assert ingest.status_code == 200, ingest.text
    exact = client.post(
        "/query",
        json={
            "text": "Continue this substantial task",
            "limit": 5,
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "work_refs": [scope["work_ref"]],
            "container_ref": "git:example.test/repo",
            "thread_ref": "scope-user",
            "visibility": "private",
        },
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["results"][0]["source_item_id"] == ingest.json()[
        "source_item_id"
    ]


@pytest.mark.skipif(os.name == "nt", reason="OpenCode structural discovery is unsupported on Windows")
def test_opencode_scope_work_ref_round_trips_into_exact_http_search(
    client,
    tmp_path: Path,
) -> None:
    repo = _repo_metadata(tmp_path / "opencode-repo")
    captured = _opencode_prompt_scope(repo, tmp_path / "opencode-home")
    assert captured["refs"] == ["git-branch:fix/alpha"]
    assert captured["payload"]["metadata"]["pallium_work_refs"] == [
        "git-branch:fix/alpha",
        "agent-workflow:alpha",
        "EXPLICIT-REF",
    ]

    ingest = _ingest(client, captured["payload"])
    assert ingest.status_code == 200, ingest.text
    exact = client.post(
        "/query",
        json={
            "text": "Continue this substantial task",
            "limit": 5,
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "work_refs": captured["refs"],
            "container_ref": captured["payload"]["container_ref"],
            "thread_ref": "oc-scope",
            "visibility": "private",
        },
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["results"][0]["source_item_id"] == ingest.json()[
        "source_item_id"
    ]


@pytest.mark.parametrize(
    "host,relative",
    (("codex", "codex/hooks"), ("claude", "claude-code/hooks")),
)
def test_python_relay_early_return_includes_structural_work_ref(
    host: str,
    relative: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load(
        f"{host}_relay_scope",
        Path("integrations") / relative / "user_prompt_submit.py",
        monkeypatch,
    )
    payload = {
        "cwd": str(_repo_metadata(tmp_path / host)),
        "session_id": f"{host}-relay",
        "prompt": "Continue this substantial task",
    }
    original_discover = module.discover_work_refs
    discoveries = 0
    monkeypatch.setattr(module, "read_hook_input", lambda _stream=None: payload)

    def discover(cwd):
        nonlocal discoveries
        discoveries += 1
        return original_discover(cwd)

    monkeypatch.setattr(module, "discover_work_refs", discover)
    monkeypatch.setattr(
        module, "resolve_container_ref", lambda *_a: "git:example.test/repo"
    )
    monkeypatch.setattr(module, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(module, "check_dedup", lambda *_a: False)
    monkeypatch.setattr(module, "get_pending_relay_closes", lambda *_a: [])
    if hasattr(module, "register_claude_wake"):
        monkeypatch.setattr(
            module, "register_claude_wake", lambda *_a, **_k: None
        )
    monkeypatch.setattr(module, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "acknowledge_relay", lambda *_a, **_k: None)
    monkeypatch.setattr(
        module,
        "pallium_request",
        lambda *_a, **_k: pytest.fail("Relay early return must not ingest"),
    )
    monkeypatch.setattr(
        module,
        "relay_request",
        lambda *_a, **_k: {
            "deliveries": [
                {
                    "delivery_id": "d-1",
                    "claim_token": "c-1",
                    "message_id": "m-1",
                    "sender_runtime": "other",
                    "sender_session_ref": "s-1",
                    "payload": "handoff",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        },
    )
    if hasattr(module, "emit_context"):
        monkeypatch.setattr(module, "emit_context", lambda text, _event: print(text))

    with pytest.raises(SystemExit):
        module.main()

    assert discoveries == 1
    assert '"work_ref":"git-branch:fix/alpha"' in capsys.readouterr().out
