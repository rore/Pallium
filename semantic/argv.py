"""Shell-word tokenizer shared across ``operational_fact`` and ``reconnaissance``.

Extracted here (from ``semantic/operational_fact.py`` in PR 3 of the
operational_fact redesign, 2026-07-02) so the reconnaissance-verb
predicates and the legacy artifact extractor use the SAME tokenizer.
Divergence between the two would recreate PR 2's heredoc-body bug in
subtle ways.

Not a full shell parser. Sufficient for extracting the argv head of a
command line while respecting the shell-word boundaries that matter for
recognizing where a logical unit ends: heredoc markers, redirects,
pipes, and command separators.
"""

from __future__ import annotations

from typing import Final


_WRAPPER_COMMANDS: Final[frozenset[str]] = frozenset({
    "env", "sudo", "time", "xargs", "nice", "nohup", "exec",
})


def shell_word_head(cmd: str) -> str:
    """Return the portion of ``cmd`` up to the first unquoted
    shell-word boundary.

    Boundaries: ``<<`` (heredoc), ``>`` / ``>>`` (redirect),
    ``|`` (pipe), ``;`` (statement separator), ``&&`` / ``||``
    (short-circuit). Quotes are respected — a ``;`` inside single
    or double quotes is text, not a boundary.

    Not a full shell parser. Sufficient to prevent heredoc bodies
    and pipeline tails from being scanned as if they were argv.
    """
    if not cmd:
        return cmd
    quote: str | None = None
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            i += 1
            continue
        # 2-char operators (must check before single-char to prefer
        # the longer match).
        two = cmd[i:i + 2]
        if two in ("<<", ">>", "&&", "||"):
            return cmd[:i]
        # Single-char boundaries.
        if ch in ("|", ">", ";"):
            return cmd[:i]
        i += 1
    return cmd


def iter_argv_head(cmd: str) -> tuple[str, ...]:
    """Split argv respecting simple single/double quoting.

    Not a full shell parser. Sufficient for extracting the command name
    and immediate subcommand for family + role classification and for
    the reconnaissance-verb predicates in PR 3.

    Tokenization stops at the first unquoted shell-word boundary — see
    :func:`shell_word_head`.
    """
    if not cmd:
        return ()
    # Truncate at the first unquoted shell-word boundary so downstream
    # regex/token consumers only see the primary argv slice.
    cmd = shell_word_head(cmd)
    tokens: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in cmd:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
            continue
        if ch in ('"', "'"):
            quote = ch
            continue
        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tuple(tokens)


def strip_wrappers(argv: tuple[str, ...]) -> tuple[str, ...]:
    """Peel ``env``, ``sudo``, etc. off the front of an argv list."""
    while argv:
        head = argv[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        # Strip ``env FOO=bar ...`` including env-var assignments.
        if head == "env":
            argv = argv[1:]
            while argv and "=" in argv[0] and not argv[0].startswith(("-", "/", "\\", ".")):
                argv = argv[1:]
            continue
        if head in _WRAPPER_COMMANDS:
            argv = argv[1:]
            continue
        break
    return argv


def argv_basename(head: str) -> str:
    """Return the case-normalized program basename from an argv[0] token.

    ``C:\\Python312\\python.exe`` → ``python.exe``. Strips both POSIX
    and Windows path separators. Callers typically also strip the
    ``.exe`` suffix for family classification — kept here as a light
    helper to reduce duplication.
    """
    if not head:
        return ""
    tail = head.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return tail.lower()


__all__ = [
    "shell_word_head",
    "iter_argv_head",
    "strip_wrappers",
    "argv_basename",
]
