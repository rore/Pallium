from __future__ import annotations

import shlex

COMMAND_COMPLETIONS = (
    "/new-conversation",
    "/artifact",
    "/debug",
    "/exit",
    "/export",
    "/fork",
    "/help",
    "/items",
    "/local-context",
    "/mode",
    "/query",
    "/query-debug",
    "/quit",
    "/replay",
    "/save",
    "/scope",
    "/show",
    "/turn",
)

ARGUMENT_COMPLETIONS = {
    "/debug": ("on", "off"),
    "/fork": ("--new-session",),
    "/local-context": ("true", "false", "clear"),
    "/mode": ("chat", "chat-lite", "manual", "replay"),
    "/scope": ("show",),
    "/show": ("scope",),
    "/turn": ("new_thread", "same_thread", "same_thread_continuation", "resumed_session", "new_session", "clear"),
}

ROLE_LABELS = {
    "agent": "agent",
    "debug": "debug",
    "error": "error",
    "system": "system",
    "warning": "warning",
}

ANSI_CODES = {
    "agent": "92",
    "debug": "90",
    "error": "91",
    "prompt": "96",
    "system": "36",
    "warning": "33",
}
ANSI_RESET = "\x1b[0m"
PROMPT_TOOLKIT_AVAILABLE = False
ANSI = None
CompleterBase = object
CompletionType = None
PromptSessionType = None

try:
    from prompt_toolkit import PromptSession as PromptSessionType
    from prompt_toolkit.completion import Completer as CompleterBase
    from prompt_toolkit.completion import Completion as CompletionType
    from prompt_toolkit.formatted_text import ANSI

    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    pass


def _ansi_wrap(text: str, color_key: str) -> str:
    color = ANSI_CODES.get(color_key)
    if not color or not text:
        return text
    return f"\x1b[{color}m{text}{ANSI_RESET}"


def format_prompt_text(text: str) -> str:
    return _ansi_wrap(text, "prompt")


def format_output_text(role: str, text: str) -> str:
    label = ROLE_LABELS.get(role)
    if not label:
        return text
    return _ansi_wrap(f"{label}: {text}", role)


def _current_token(text: str) -> str:
    if not text:
        return ""
    if text.endswith(" "):
        return ""
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    return parts[-1] if parts else text


def _parsed_parts(text: str) -> list[str]:
    if not text.strip():
        return []
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def completion_candidates(text: str) -> list[str]:
    stripped = text.lstrip()
    if not stripped.startswith("/"):
        return []
    parts = _parsed_parts(stripped)
    current = _current_token(stripped).lower()
    if not parts:
        return list(COMMAND_COMPLETIONS)
    if len(parts) == 1 and not stripped.endswith(" "):
        return [command for command in COMMAND_COMPLETIONS if command.startswith(current)]

    command = parts[0].lower()
    candidates = list(ARGUMENT_COMPLETIONS.get(command, ()))
    if stripped.endswith(" "):
        return candidates
    return [candidate for candidate in candidates if candidate.startswith(current)]


if PROMPT_TOOLKIT_AVAILABLE:
    class AgentSimulationCompleter(CompleterBase):
        def get_completions(self, document, complete_event):
            current = _current_token(document.text_before_cursor)
            for candidate in completion_candidates(document.text_before_cursor):
                yield CompletionType(candidate, start_position=-len(current))
else:
    class AgentSimulationCompleter:  # type: ignore[no-redef]
        pass


def build_terminal_io():
    from app.agent_simulation import TerminalIO

    if not PROMPT_TOOLKIT_AVAILABLE or PromptSessionType is None or ANSI is None:
        return TerminalIO()

    session = PromptSessionType(completer=AgentSimulationCompleter(), complete_while_typing=True)

    def _prompt(text: str) -> str:
        return session.prompt(ANSI(format_prompt_text(text)))

    return TerminalIO(
        input_func=_prompt,
        output_func=print,
        output_formatter=format_output_text,
    )





