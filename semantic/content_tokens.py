"""Shared content-token extraction for injection eligibility and overlap checks.

This module provides the same stopword-filtered tokenization used by INV-03
(evals/generated_exploratory/invariants.py) so that production injection checks
are aligned with what the invariant tests.
"""
from __future__ import annotations

import re

# Stopwords excluded from content overlap checks.
# Aligned with evals/generated_exploratory/invariants.py _STOPWORDS.
CONTENT_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "must", "need",
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "she",
    "it", "they", "them", "their", "its", "his", "her",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "up",
    "about", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than", "too",
    "very", "just", "also", "now", "then", "here", "there", "when",
    "where", "why", "how", "what", "which", "who", "whom", "this",
    "that", "these", "those", "if", "as",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Minimum shared prefix length for morphological variant matching.
# Aligned with evals/generated_exploratory/invariants.py _PREFIX_MATCH_MIN_LEN.
# Catches batch/batches, hold/holds, reserve/reserved, sync/syncing.
_PREFIX_MATCH_MIN_LEN = 4


def content_tokens(text: str) -> set[str]:
    """Extract lowercase content words, excluding stopwords."""
    words = set(_TOKEN_RE.findall(text.lower()))
    return words - CONTENT_STOPWORDS


def has_content_overlap(query_text: str, candidate_text: str) -> bool:
    """Check if query and candidate share at least one content word.

    Uses exact matching first, then prefix matching for morphological variants
    (singular/plural, verb forms). Aligned with INV-03's _topic_overlap strategy.
    """
    if not query_text or not candidate_text:
        return False
    q_tokens = content_tokens(query_text)
    c_tokens = content_tokens(candidate_text)
    if not q_tokens or not c_tokens:
        return False
    # Fast path: exact match
    if q_tokens & c_tokens:
        return True
    # Prefix matching for morphological variants (e.g. "batch"/"batches")
    for q in q_tokens:
        if len(q) < _PREFIX_MATCH_MIN_LEN:
            continue
        for c in c_tokens:
            if len(c) < _PREFIX_MATCH_MIN_LEN:
                continue
            prefix_len = 0
            for cq, cc in zip(q, c):
                if cq != cc:
                    break
                prefix_len += 1
            if prefix_len >= _PREFIX_MATCH_MIN_LEN:
                return True
    return False
