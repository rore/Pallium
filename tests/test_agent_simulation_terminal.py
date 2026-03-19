from __future__ import annotations

from app.agent_simulation import TerminalIO
from app.agent_simulation_terminal import (
    ARGUMENT_COMPLETIONS,
    COMMAND_COMPLETIONS,
    PROMPT_TOOLKIT_AVAILABLE,
    completion_candidates,
    format_output_text,
    build_terminal_io,
)


def test_completion_candidates_suggest_slash_commands() -> None:
    candidates = completion_candidates("/mo")

    assert "/mode" in candidates
    assert "/query" not in candidates
    assert "/mode" in COMMAND_COMPLETIONS


def test_completion_candidates_suggest_turn_arguments() -> None:
    candidates = completion_candidates("/turn re")

    assert candidates == ["resumed_session"]
    assert "resumed_session" in ARGUMENT_COMPLETIONS["/turn"]


def test_completion_candidates_suggest_scope_and_fork_arguments() -> None:
    assert completion_candidates("/scope ") == ["show"]
    assert completion_candidates("/show s") == ["scope"]
    assert completion_candidates("/fork --") == ["--new-session"]


def test_completion_candidates_ignore_plain_chat_text() -> None:
    assert completion_candidates("hello there") == []


def test_format_output_text_prefixes_and_colors_roles() -> None:
    rendered = format_output_text("agent", "ready")

    assert "agent: ready" in rendered
    assert "\x1b[" in rendered


def test_build_terminal_io_falls_back_to_plain_when_prompt_toolkit_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.agent_simulation_terminal.PROMPT_TOOLKIT_AVAILABLE", False)
    io = build_terminal_io()

    assert isinstance(io, TerminalIO)
    assert io.output_formatter is None
    assert io.prompt_formatter is None


def test_build_terminal_io_returns_styled_terminal_when_prompt_toolkit_available(monkeypatch) -> None:
    if not PROMPT_TOOLKIT_AVAILABLE:
        return

    class FakeSession:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.prompts: list[object] = []

        def prompt(self, text):
            self.prompts.append(text)
            return "typed"

    fake_session = FakeSession()

    def _factory(**kwargs):
        fake_session.kwargs = kwargs
        return fake_session

    monkeypatch.setattr("app.agent_simulation_terminal.PromptSessionType", _factory)
    io = build_terminal_io()

    assert isinstance(io, TerminalIO)
    assert io.output_formatter is not None
    assert fake_session.kwargs["complete_while_typing"] is True
    assert io.prompt("chat> ") == "typed"
    assert fake_session.prompts

