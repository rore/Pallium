"""Regression tests for Codex integration setup and hooks."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import setup_codex


def test_codex_mcp_config_uses_absolute_venv_command_and_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(setup_codex.sys, "platform", "win32")
    monkeypatch.setattr(
        setup_codex.sys,
        "executable",
        r"C:\Dev\rore\Pallium\.venv\Scripts\python.exe",
    )

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
    assert 'command = "C:/Dev/rore/Pallium/.venv/Scripts/pallium-mcp.exe"' in content
    assert 'PALLIUM_BASE_URL = "http://localhost:19836"' in content


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
    assert len(calls) == 1
    call = calls[0]
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
