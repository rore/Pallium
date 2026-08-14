"""Regression tests for Codex integration setup and hooks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.cli import setup_codex


def test_codex_mcp_config_uses_python_module_launch_and_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(setup_codex.sys, "platform", "win32")
    monkeypatch.setattr(
        setup_codex.sys,
        "executable",
        r"C:\Users\me\AppData\Roaming\uv\python\cpython-3.13.14-windows-x86_64-none\python.exe",
    )
    monkeypatch.setattr(setup_codex, "_pallium_repo_root", lambda: tmp_path)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setenv("PATH", r"C:\Windows")

    content = setup_codex._ensure_mcp_server(
        """
[mcp_servers.pallium]
command = "pallium-mcp"
args = ["--stdio"]
env = { PALLIUM_MCP_TRANSPORT = "stdio" }
""",
        port=19836,
    )

    assert content.count("[mcp_servers.pallium]") == 1
    assert (
        'command = "C:/Users/me/AppData/Roaming/uv/python/'
        'cpython-3.13.14-windows-x86_64-none/python.exe"'
    ) in content
    assert 'args = ["-m", "app.run", "mcp"]' in content
    assert 'PALLIUM_BASE_URL = "http://localhost:19836"' in content
    assert f'PYTHONPATH = "{tmp_path.as_posix()}"' in content


def test_codex_mcp_config_adds_repo_local_and_uv_venv_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "Pallium"
    local_site = repo / ".local" / "test-env" / "site-packages"
    local_site.mkdir(parents=True)
    uv_root = tmp_path / "uv"
    py_dir = uv_root / "python" / "cpython-3.13.14-windows-x86_64-none"
    py_dir.mkdir(parents=True)
    pallium_site = uv_root / "pallium-venv" / "Lib" / "site-packages"
    (pallium_site / "win32" / "lib").mkdir(parents=True)
    (pallium_site / "pywin32_system32").mkdir(parents=True)

    monkeypatch.setattr(setup_codex.sys, "platform", "win32")
    monkeypatch.setattr(setup_codex.sys, "executable", str(py_dir / "python.exe"))
    monkeypatch.setattr(setup_codex, "_pallium_repo_root", lambda: repo)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setenv("PATH", r"C:\Windows")

    content = setup_codex._ensure_mcp_server("", port=19836)

    for expected in (
        repo,
        local_site,
        pallium_site,
        pallium_site / "win32",
        pallium_site / "win32" / "lib",
    ):
        assert str(expected).replace("\\", "/") in content
    assert str(pallium_site / "pywin32_system32").replace("\\", "/") in content


def test_codex_hooks_use_absolute_commands_without_literal_quotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        setup_codex.sys,
        "executable",
        r"C:\Dev\rore\Pallium\.venv\Scripts\python.exe",
    )
    monkeypatch.setattr(
        setup_codex,
        "_hooks_dir",
        lambda: Path(r"C:\Dev\rore\Pallium\integrations\codex\hooks"),
    )

    hooks_data = setup_codex._register_hooks({})
    commands = [
        hook["command"]
        for entries in hooks_data["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
    ]

    assert len(commands) == 3
    assert all(command.startswith("C:/Dev/rore/Pallium/.venv/Scripts/python.exe ") for command in commands)
    assert all('"' not in command for command in commands)
    assert any(command.endswith("/session_start.py") for command in commands)
    assert any(command.endswith("/user_prompt_submit.py") for command in commands)
    assert any(command.endswith("/stop.py") for command in commands)


def test_codex_hook_registration_self_heals_stale_pallium_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        setup_codex.sys,
        "executable",
        r"C:\Dev\rore\Pallium\.venv\Scripts\python.exe",
    )
    monkeypatch.setattr(
        setup_codex,
        "_hooks_dir",
        lambda: Path(r"C:\Dev\rore\Pallium\integrations\codex\hooks"),
    )

    stale_hooks = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": '"C:/Dev/rore/Pallium/.venv/Scripts/python.exe" "C:/Dev/rore/Pallium/integrations/codex/hooks/stop.py"',
                            "timeout": 15,
                        }
                    ]
                },
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "C:/other/tool.exe",
                            "timeout": 15,
                        }
                    ]
                },
            ]
        }
    }

    cleaned = setup_codex._unregister_hooks(stale_hooks)
    registered = setup_codex._register_hooks(cleaned)

    stop_commands = [
        hook["command"]
        for entry in registered["hooks"]["Stop"]
        for hook in entry["hooks"]
    ]
    assert "C:/other/tool.exe" in stop_commands
    expected_stop = (
        "C:/Dev/rore/Pallium/.venv/Scripts/python.exe "
        "C:/Dev/rore/Pallium/integrations/codex/hooks/stop.py"
    )
    assert stop_commands.count(expected_stop) == 1
    assert all(command.count("stop.py") == 1 for command in stop_commands if "Pallium" in command)


def test_codex_agents_block_is_replaced_when_setup_runs_again() -> None:
    existing = "\n".join([
        "before",
        "<!-- pallium:start -->",
        "old mandatory instructions",
        "<!-- pallium:end -->",
        "after",
    ])
    replacement = "\n".join([
        "<!-- pallium:start -->",
        "new thin-client instructions",
        "<!-- pallium:end -->",
    ])

    updated = setup_codex._replace_agents_md_block(existing, replacement)

    assert "before" in updated
    assert "after" in updated
    assert "old mandatory instructions" not in updated
    assert "new thin-client instructions" in updated


def test_codex_stop_hook_ingests_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    from integrations.codex.hooks import stop

    calls: list[dict] = []

    monkeypatch.setattr(
        stop,
        "read_hook_input",
        lambda: {
            "cwd": r"C:\Dev\rore\Pallium",
            "session_id": "session-1",
            "transcript_path": "transcript.jsonl",
        },
    )
    monkeypatch.setattr(stop, "read_turn", lambda _: stop._common.TurnData(
        assistant_text="assistant response",
        tool_calls=[],
        has_productive_action=False,
    ))
    monkeypatch.setattr(stop, "build_work_trace_metadata", lambda _: None)
    monkeypatch.setattr(stop, "resolve_container_ref", lambda _cwd, _session_id: "git:github.com/rore/pallium")
    monkeypatch.setattr(stop, "derive_actor_ref", lambda: "Rotem")

    def fake_request(method: str, path: str, payload: object, *, quiet: bool = False) -> None:
        calls.append({"method": method, "path": path, "payload": payload, "quiet": quiet})

    monkeypatch.setattr(stop, "pallium_request", fake_request)

    with pytest.raises(SystemExit) as exc:
        stop.main()

    assert exc.value.code == 0
    # Phase 5b: stop hook now also issues a populator GET after ingest.
    # The fake returns None so the populator no-ops. Verify the ingest
    # call is present.
    ingest_calls = [c for c in calls if c["path"] == "/items"]
    assert len(ingest_calls) == 1
    call = ingest_calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/items"
    assert call["quiet"] is True

    payload = call["payload"]
    assert isinstance(payload, list)
    assert len(payload) == 1
    item = payload[0]
    assert item["source_id"].startswith("cdx-")
    assert item == {
        "source_type": "codex",
        "source_id": item["source_id"],
        "content_type": "text/plain",
        "content": "assistant response",
        "role": "assistant",
        "agent_ref": "codex",
        "container_ref": "git:github.com/rore/pallium",
        "thread_ref": "session-1",
        "actor_ref": "Rotem",
        "visibility": "private",
        "artifact_kind": "message",
    }


def test_codex_transcript_parser_reads_desktop_response_item_shape(tmp_path: Path) -> None:
    from integrations.codex.hooks.common import read_last_assistant_turn

    transcript = tmp_path / "codex.jsonl"
    transcript.write_text(
        "\n".join([
            '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"question"}]}}',
            '{"type":"response_item","payload":{"type":"function_call","name":"shell_command","arguments":"{}"}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"first answer"}]}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"final answer"}]}}',
        ]),
        encoding="utf-8",
    )

    assert read_last_assistant_turn(str(transcript)) == "final answer"


def test_codex_agents_block_keeps_manual_memory_tools_optional() -> None:
    agents_block = Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8")

    assert "MANDATORY" not in agents_block
    assert "MUST call `pallium_rate_memory` for EACH injected memory block" not in agents_block
    assert "If an injected card has `[+source]` and you rated it relevant" not in agents_block
    assert "`pallium_query`" in agents_block
    assert "`pallium_expand`" in agents_block


def test_codex_agents_block_permits_deliberate_historical_pull() -> None:
    agents_block = Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8")

    # Permit/encourage line for a deliberate historical pull, and the P1 tools
    # are exposed.
    assert "Picking up prior work?" in agents_block
    assert "`pallium_search_history`" in agents_block
    assert "`pallium_expand_source`" in agents_block

    # The blanket "Query every turn" discouragement is gone, but the anti-dup
    # clause is retained.
    assert "Query every turn" not in agents_block
    assert "re-query for something already in the injected block" in agents_block


def test_codex_mcp_json_has_no_stdio_noop() -> None:
    mcp_json = json.loads(Path("integrations/codex/.mcp.json").read_text(encoding="utf-8"))
    args = mcp_json["mcp_servers"]["pallium"].get("args", [])
    assert "--stdio" not in args


def test_codex_guidance_strength_selects_block_variant() -> None:
    tool_only = setup_codex._build_agents_md_block("tool-only")
    strong = setup_codex._build_agents_md_block("strong")

    # Arm marker recorded inside each installed block.
    assert "<!-- pallium:guidance-strength=tool-only -->" in tool_only
    assert "<!-- pallium:guidance-strength=strong -->" in strong

    # The strong variant appends the resume directive; tool-only does not.
    assert "## Resuming prior work" in strong
    assert "## Resuming prior work" not in tool_only
    assert strong != tool_only

    # Both variants preserve the Codex block invariants.
    for variant in (tool_only, strong):
        assert "MANDATORY" not in variant
        assert "`pallium_query`" in variant
        assert "`pallium_expand`" in variant


def test_codex_build_block_rejects_unknown_strength() -> None:
    with pytest.raises(ValueError):
        setup_codex._build_agents_md_block("aggressive")


def test_codex_reinstall_replaces_block_on_strength_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agents_path = tmp_path / "AGENTS.md"
    monkeypatch.setattr(setup_codex, "_codex_agents_md_path", lambda: agents_path)

    setup_codex._append_agents_md_block("tool-only")
    first = agents_path.read_text(encoding="utf-8")
    assert "<!-- pallium:guidance-strength=tool-only -->" in first
    assert "## Resuming prior work" not in first

    setup_codex._append_agents_md_block("strong")
    second = agents_path.read_text(encoding="utf-8")
    assert "<!-- pallium:guidance-strength=strong -->" in second
    assert "## Resuming prior work" in second
    # Marker block is replaced, not duplicated.
    assert second.count("<!-- pallium:start -->") == 1
    assert first != second


def test_codex_setup_deploys_and_removes_skill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skill_dir = tmp_path / ".codex" / "skills" / "pallium-memory"
    monkeypatch.setattr(setup_codex, "_codex_skill_dir", lambda: skill_dir)

    # Install deploys the SKILL.md into the discovery dir with expected content.
    setup_codex._install_skill()
    dest = skill_dir / "SKILL.md"
    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    assert "Pallium Memory Workflow" in content
    assert "pallium_search_history" in content

    # Reinstall is idempotent (overwrites, no duplication/error).
    setup_codex._install_skill()
    assert dest.read_text(encoding="utf-8") == content

    # Uninstall removes the deployed skill directory.
    setup_codex._remove_skill()
    assert not dest.exists()
    assert not skill_dir.exists()


def test_codex_skill_historical_lookup_documents_scope_params() -> None:
    skill = Path(
        "integrations/codex/skills/pallium-memory/SKILL.md"
    ).read_text(encoding="utf-8")

    # The historical-lookup section names both scope params for the P1 tools
    # and preserves the global-scope exception wording.
    assert "`pallium_search_history` and `pallium_expand_source`" in skill
    assert "`container_ref`" in skill
    assert '`visibility: "private"`' in skill
    assert '`visibility: "global"` with `actor_ref`' in skill


@pytest.mark.parametrize(
    "hook_name,stdin_payload",
    [
        (
            "session_start.py",
            {"session_id": "regression-test", "cwd": ".", "source": "startup"},
        ),
        (
            "user_prompt_submit.py",
            {"session_id": "regression-test", "cwd": ".", "prompt": "x"},
        ),
        (
            "stop.py",
            {"session_id": "regression-test", "cwd": ".", "transcript_path": ""},
        ),
    ],
)
def test_codex_hooks_import_cleanly_as_subprocess(
    hook_name: str, stdin_payload: dict, tmp_path: Path
) -> None:
    """Each hook must import cleanly when run as a subprocess (the way Codex invokes it).

    Regression for a silent hook crash: importlib.util.spec_from_file_location loads
    common.py without registering it in sys.modules, but @dataclass needs the module
    in sys.modules during class creation on Python 3.13. Missing the registration
    line crashes hooks at import time, before main() runs — and Codex Desktop swallows
    stderr, so the failure is invisible. user_prompt_submit.py was missing this line
    for ~3 weeks before being noticed.

    The bug is unreachable via `from integrations.codex.hooks import X`, so this test
    invokes each hook the way Codex actually does: subprocess + stdin.
    """
    hook_path = Path("integrations/codex/hooks") / hook_name
    assert hook_path.exists()

    stdin_payload = {**stdin_payload, "cwd": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, (
        f"{hook_name} crashed: stderr={result.stderr!r} stdout={result.stdout!r}"
    )
    assert "Traceback" not in result.stderr, (
        f"{hook_name} raised exception: {result.stderr}"
    )
