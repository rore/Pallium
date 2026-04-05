"""Centralized tokenization and text-normalization utilities.

Every lexical path (indexing, search, overlap checks) must agree on how raw
text becomes tokens.  This module is the single source of truth for that
contract.  It handles Latin, Hebrew, Arabic, CJK, Cyrillic, and Korean
scripts, strips combining marks (diacritics, niqud, Arabic vowels), and
produces a deterministic normalized form suitable for indexing and comparison.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Token pattern — Unicode-aware, CJK-character-per-token
# ---------------------------------------------------------------------------

_CJK_RANGES = (
    "\u3040-\u309F"   # Hiragana
    "\u30A0-\u30FF"   # Katakana
    "\u3400-\u4DBF"   # CJK Extension A
    "\u4E00-\u9FFF"   # CJK Unified Ideographs
    "\uF900-\uFAFF"   # CJK Compatibility Ideographs
)
_CJK_CHAR = f"[{_CJK_RANGES}]"
_NON_CJK_WORD = f"[^\\W_{_CJK_RANGES}]+"

TOKEN_PATTERN = re.compile(f"{_CJK_CHAR}|{_NON_CJK_WORD}", re.UNICODE)

# ---------------------------------------------------------------------------
# Sentence splitting (used by semantic/common.py)
# ---------------------------------------------------------------------------

SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def strip_combining_marks(text: str) -> str:
    """Strip combining marks (Hebrew niqud, Arabic vowels, Latin diacritics).

    "d\u00e9cision" \u2192 "decision", "\u05e1\u05b4\u05e4\u05b0\u05e8\u05b4\u05d9\u05bc\u05b8\u05d4" \u2192 "\u05e1\u05e4\u05e8\u05d9\u05d4", "\u0645\u064e\u0631\u0652\u062d\u064e\u0628\u064b\u0627" \u2192 "\u0645\u0631\u062d\u0628\u0627".
    """
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_for_index(text: str) -> str:
    """Normalize text for lexical indexing and text comparison."""
    return " ".join(TOKEN_PATTERN.findall(strip_combining_marks(text).lower()))


def tokenize_text(text: str) -> list[str]:
    """Tokenize text into a list of normalized tokens."""
    return TOKEN_PATTERN.findall(strip_combining_marks(text).lower())
