"""Phase 5b populator helpers — match injected memories against the
assistant's response to populate `memory_usage_audit` rows.

Pure functions; no I/O. Tested independently from the Stop hook.

See: docs/specs/2026-06-27-injection-policy-abstention.md (Phase 5b).
"""

from __future__ import annotations

import re


# Minimum length for a verbatim snippet to count as a match.
# Architect review: 60 chars + word-content rule chosen over 40 to
# reduce false positives from quoted code identifiers / paths.
VERBATIM_SNIPPET_MIN_CHARS = 60

# A word match window must contain at least one **space-bounded**
# alphabetic token of at least this many characters. Boundary check
# is what rejects matches that are pure code identifiers / paths
# (which are technically full of "function", "path", etc. as
# substrings but contain no whitespace).
WORD_TOKEN_MIN_ALPHA = 4

# Maximum text size we'll scan per call. Larger inputs are truncated
# (we keep the head). The Stop hook already enforces a 20KB ceiling on
# assistant_text; this is a defensive cap inside the matcher.
MATCH_TEXT_MAX_CHARS = 50_000


# A space-bounded word token: alpha-only, at least WORD_TOKEN_MIN_ALPHA
# characters, surrounded by whitespace or string boundaries. The
# requirement that it sit between whitespace is what makes pure code /
# pure path windows fail the filter — those contain alpha sub-runs
# inside identifiers but no actual whitespace.
_WORD_TOKEN_RE = re.compile(
    rf"(?:^|\s)([a-zA-Z]{{{WORD_TOKEN_MIN_ALPHA},}})(?=\s|$)"
)


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to a single space.

    Verbatim matching ignores formatting differences between the
    injected memory text and the assistant's quote of it.
    """
    return re.sub(r"\s+", " ", text).strip()


def _has_real_word(window: str) -> bool:
    """Window must contain a space-bounded >=4-letter alpha word.

    Filters matches that are pure code / paths / identifiers — those
    rarely indicate the agent quoted a memory; they're usually
    coincidental occurrences of file paths or function names.

    Requirements:
    1. Window contains at least one literal space (no-whitespace
       windows are necessarily not natural prose).
    2. Window contains a >=4-letter alpha word bounded by whitespace
       (so `function` inside `function_call_x(...)` does NOT qualify).
    """
    if " " not in window:
        return False
    return _WORD_TOKEN_RE.search(window) is not None


def find_id_quote(
    memory_object_id: str,
    response_text: str,
) -> bool:
    """Return True iff `ref:<memory_object_id>` appears verbatim in
    `response_text`. High-precision signal; agents sometimes cite
    memories explicitly when calling `pallium_flag_memory`.
    """
    if not memory_object_id or not response_text:
        return False
    return f"ref:{memory_object_id}" in response_text


def find_verbatim_snippet(
    memory_text: str,
    response_text: str,
    *,
    min_chars: int = VERBATIM_SNIPPET_MIN_CHARS,
) -> bool:
    """Return True iff a window of >= `min_chars` from `memory_text`
    (whitespace-normalized) appears in `response_text`
    (whitespace-normalized) AND that window contains at least one real
    word of >= 4 alpha characters.

    Both texts are truncated at `MATCH_TEXT_MAX_CHARS` defensively.
    """
    if not memory_text or not response_text:
        return False
    mem = _normalize_whitespace(memory_text)[:MATCH_TEXT_MAX_CHARS]
    resp = _normalize_whitespace(response_text)[:MATCH_TEXT_MAX_CHARS]
    if len(mem) < min_chars:
        return False
    # Sliding window over `mem` of length `min_chars`. Step by 1 so we
    # don't miss boundary alignments. Cheap because both strings are
    # small.
    for i in range(0, len(mem) - min_chars + 1):
        window = mem[i:i + min_chars]
        if not _has_real_word(window):
            continue
        if window in resp:
            return True
    return False


def classify_memory_reference(
    *,
    memory_object_id: str,
    memory_text: str,
    response_text: str,
) -> tuple[bool, str | None]:
    """Run both heuristics in priority order.

    Returns `(referenced, reference_kind)`:
      - (True, "id_quote") if the agent quoted the memory's ref.
      - (True, "verbatim_snippet") if a >=60-char real-word window
        from the memory text appears in the response.
      - (False, None) otherwise.

    id_quote is tested first because it's the higher-precision signal.
    """
    if find_id_quote(memory_object_id, response_text):
        return True, "id_quote"
    if find_verbatim_snippet(memory_text, response_text):
        return True, "verbatim_snippet"
    return False, None
