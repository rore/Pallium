"""Pure matching helpers for memory usage-audit population."""

from __future__ import annotations

import re

VERBATIM_SNIPPET_MIN_CHARS = 60
WORD_TOKEN_MIN_ALPHA = 4
MATCH_TEXT_MAX_CHARS = 50_000
_WORD_TOKEN_RE = re.compile(
    rf"(?:^|\s)([a-zA-Z]{{{WORD_TOKEN_MIN_ALPHA},}})(?=\s|$)"
)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _has_real_word(window: str) -> bool:
    return " " in window and _WORD_TOKEN_RE.search(window) is not None


def find_id_quote(memory_object_id: str, response_text: str) -> bool:
    if not memory_object_id or not response_text:
        return False
    return f"ref:{memory_object_id}" in response_text


def find_verbatim_snippet(
    memory_text: str,
    response_text: str,
    *,
    min_chars: int = VERBATIM_SNIPPET_MIN_CHARS,
) -> bool:
    if not memory_text or not response_text:
        return False
    mem = _normalize_whitespace(memory_text)[:MATCH_TEXT_MAX_CHARS]
    resp = _normalize_whitespace(response_text)[:MATCH_TEXT_MAX_CHARS]
    if len(mem) < min_chars or len(resp) < min_chars:
        return False
    # Build the fixed-width response index once; each candidate lookup is O(1)
    # average instead of rescanning the response for every memory window.
    response_windows = {resp[i:i + min_chars] for i in range(len(resp) - min_chars + 1)}
    return any(
        _has_real_word(window) and window in response_windows
        for i in range(len(mem) - min_chars + 1)
        for window in (mem[i:i + min_chars],)
    )


def classify_memory_reference(
    *,
    memory_object_id: str,
    memory_text: str,
    response_text: str,
) -> tuple[bool, str | None]:
    if find_id_quote(memory_object_id, response_text):
        return True, "id_quote"
    if find_verbatim_snippet(memory_text, response_text):
        return True, "verbatim_snippet"
    return False, None