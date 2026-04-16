"""Regression tests for text normalization.
Documents Unicode-aware tokenization behavior.
"""

from __future__ import annotations

import pytest

from core.models import QueryResultItem
from retrieval.lexical import tokenize_query
from semantic.common import content_tokens, normalize_for_index, strip_diacritics


# ---------------------------------------------------------------------------
# normalize_for_index
# ---------------------------------------------------------------------------


class TestNormalizeForIndex:
    """Tests for normalize_for_index: lowercases, strips combining marks
    (diacritics/niqud/vowels), and tokenizes with Unicode-aware pattern."""

    def test_english_text_lowercased(self):
        assert normalize_for_index("Hello World") == "hello world"

    def test_diacritics_folded_to_ascii(self):
        assert normalize_for_index("décision über catálogo") == "decision uber catalogo"

    def test_punctuation_stripped(self):
        assert normalize_for_index("hello, world! how?") == "hello world how"

    def test_digits_preserved(self):
        assert normalize_for_index("Python3 bge-small-en") == "python3 bge small en"

    def test_hebrew_text_tokenized(self):
        """Hebrew characters are tokenized by the Unicode-aware pattern."""
        assert normalize_for_index("שלום עולם") == "שלום עולם"

    def test_cjk_text_tokenized(self):
        """CJK characters are tokenized (one token per character)."""
        assert normalize_for_index("今天天气很好") == "今 天 天 气 很 好"

    def test_mixed_hebrew_english_preserves_both(self):
        """Both Latin and Hebrew tokens survive the Unicode-aware regex."""
        assert normalize_for_index("hello שלום world") == "hello שלום world"


# ---------------------------------------------------------------------------
# content_tokens
# ---------------------------------------------------------------------------


class TestContentTokens:
    """Tests for content_tokens: tokenizes via normalize_for_index, removes
    English stopwords, expands plural stems."""

    def test_english_with_stopwords_removed(self):
        tokens = content_tokens("the quick brown fox")
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens
        assert "the" not in tokens

    def test_plural_expansion_included(self):
        """'reservations' should produce both the original and the
        singular stem 'reservation'."""
        tokens = content_tokens("reservations")
        assert "reservations" in tokens
        assert "reservation" in tokens

    def test_hebrew_returns_hebrew_tokens(self):
        """Pure Hebrew is now tokenized by the Unicode-aware pattern."""
        tokens = content_tokens("שלום עולם")
        assert "שלום" in tokens
        assert "עולם" in tokens

    def test_cjk_single_character_tokens_preserved(self):
        """CJK tokens are single characters by design and must survive content filtering."""
        tokens = content_tokens("今天天气很好")
        assert "今" in tokens
        assert "天" in tokens
        assert "气" in tokens

    def test_possessive_suffix_fragment_removed(self):
        """Possessive apostrophes must not leave a junk overlap token like 's'."""
        tokens = content_tokens("tomorrow's SQLAlchemy's")
        assert "tomorrow" in tokens
        assert "sqlalchemy" in tokens
        assert "s" not in tokens

    def test_two_character_technical_tokens_preserved(self):
        """Short technical tokens still matter for overlap and must remain available."""
        tokens = content_tokens("AI DB S3")
        assert "ai" in tokens
        assert "db" in tokens
        assert "s3" in tokens

    def test_all_stopwords_returns_empty_set(self):
        """Input consisting solely of stopwords produces an empty set."""
        assert content_tokens("is a the") == set()


# ---------------------------------------------------------------------------
# strip_diacritics
# ---------------------------------------------------------------------------


class TestStripDiacritics:
    """Tests for strip_diacritics: NFKD decomposition + combining-mark removal."""

    def test_latin_diacritics_folded(self):
        assert strip_diacritics("décision") == "decision"

    def test_hebrew_niqud_stripped(self):
        """Hebrew vowel points (niqud) are combining marks and should be
        removed, leaving the base consonant letters intact."""
        # shin + shva + lamed + vav + dagesh + mem
        with_niqud = "\u05e9\u05b0\u05dc\u05d5\u05bc\u05dd"
        stripped = strip_diacritics(with_niqud)
        # Base letters: shin lamed vav mem
        assert stripped == "\u05e9\u05dc\u05d5\u05dd"

    def test_plain_ascii_unchanged(self):
        assert strip_diacritics("hello") == "hello"


# ---------------------------------------------------------------------------
# tokenize_query  (retrieval/lexical.py)
# ---------------------------------------------------------------------------


class TestTokenizeQuery:
    """Tests for tokenize_query: tokenizes, expands stems, returns sorted
    deduplicated tuple."""

    def test_hebrew_returns_hebrew_tokens(self):
        """Hebrew input is now tokenized by the Unicode-aware pattern."""
        tokens = tokenize_query("שלום עולם")
        assert "שלום" in tokens
        assert "עולם" in tokens

    def test_english_tokens_present(self):
        tokens = tokenize_query("hello world")
        assert "hello" in tokens
        assert "world" in tokens


# ---------------------------------------------------------------------------
# _candidate_has_content_overlap
# ---------------------------------------------------------------------------


class TestCandidateHasContentOverlap:
    """Tests for _candidate_has_content_overlap: content-overlap injection gate."""

    @staticmethod
    def _make_item(payload: dict | None = None, excerpt: str | None = None) -> QueryResultItem:
        """Build a minimal QueryResultItem for testing."""
        return QueryResultItem(
            result_kind="memory",
            score=100,
            evidence=[],
            payload=payload,
            excerpt=excerpt,
        )

    def test_cross_language_bypass_hebrew_query_english_candidate(self):
        """When query is Hebrew-only and candidate is English-only, the
        script-mismatch bypass defers to vector similarity (returns True)."""
        from semantic.agent_conversation_memory_routing_selection import (
            _candidate_has_content_overlap,
        )

        item = self._make_item(payload={"summary": "some english summary"})
        result = _candidate_has_content_overlap(item, "שלום עולם")
        assert result is True

    def test_english_tokens_with_overlap_returns_true(self):
        """When both query and candidate share at least one content word,
        the gate returns True."""
        from semantic.agent_conversation_memory_routing_selection import (
            _candidate_has_content_overlap,
        )

        item = self._make_item(payload={"summary": "the quick brown fox"})
        result = _candidate_has_content_overlap(item, "tell me about the fox")
        assert result is True

    def test_english_tokens_no_overlap_returns_false(self):
        """When query and candidate share zero content words, the gate
        returns False."""
        from semantic.agent_conversation_memory_routing_selection import (
            _candidate_has_content_overlap,
        )

        item = self._make_item(payload={"summary": "the quick brown fox"})
        result = _candidate_has_content_overlap(item, "database migration plan")
        assert result is False

    def test_possessive_fragment_does_not_count_as_overlap(self):
        """Apostrophe suffix fragments like 's' must not satisfy overlap on their own."""
        from semantic.agent_conversation_memory_routing_selection import (
            _candidate_has_content_overlap,
        )

        item = self._make_item(
            payload={
                "investigation_outcome": "SQLAlchemy's connection pool caused the OOM.",
                "rationale": "The fix capped max_overflow after the database slowed down.",
            }
        )
        result = _candidate_has_content_overlap(
            item,
            "Can you help me draft tomorrow's standup agenda?",
        )
        assert result is False


# ---------------------------------------------------------------------------
# TestCoreTextTokenizer — direct tests for core/text.py functions
# ---------------------------------------------------------------------------


class TestCoreTextTokenizer:
    """Tests for TOKEN_PATTERN, strip_combining_marks, normalize_for_index,
    and tokenize_text from core/text.py across multiple scripts."""

    def test_latin_tokens(self):
        from core.text import tokenize_text
        assert tokenize_text("hello world") == ["hello", "world"]

    def test_digits_preserved_in_token(self):
        from core.text import tokenize_text
        assert tokenize_text("Python3") == ["python3"]

    def test_hyphen_splits_tokens(self):
        from core.text import tokenize_text
        assert tokenize_text("bge-small-en") == ["bge", "small", "en"]

    def test_underscore_splits_tokens(self):
        from core.text import tokenize_text
        assert tokenize_text("hello_world") == ["hello", "world"]

    def test_hebrew_tokens(self):
        from core.text import tokenize_text
        assert tokenize_text("שלום עולם") == ["שלום", "עולם"]

    def test_hebrew_niqud_stripped_to_single_token(self):
        """Hebrew with niqud (vowel points) should collapse to a single
        base-letter token with combining marks removed."""
        from core.text import tokenize_text
        # סִפְרִיָּה — samekh+hiriq, pe+shva, resh+hiriq, yod+qamats+dagesh, he
        assert tokenize_text("סִפְרִיָּה") == ["ספריה"]

    def test_arabic_tokens(self):
        from core.text import tokenize_text
        assert tokenize_text("مرحبا") == ["مرحبا"]

    def test_arabic_vowels_stripped(self):
        """Arabic with tashkil (vowel marks) should collapse to base letters."""
        from core.text import tokenize_text
        # مَرْحَبًا — meem+fatha, ra+sukun, ha+fatha, ba+tanwin-fatha, alef
        assert tokenize_text("مَرْحَبًا") == ["مرحبا"]

    def test_cyrillic_tokens(self):
        from core.text import tokenize_text
        assert tokenize_text("Привет мир") == ["привет", "мир"]

    def test_cjk_character_per_token(self):
        from core.text import tokenize_text
        assert tokenize_text("今天天气") == ["今", "天", "天", "气"]

    def test_korean_tokens(self):
        """Korean Hangul syllables are decomposed into Jamo by NFKD
        normalization, but still produce two word-level tokens."""
        from core.text import tokenize_text
        tokens = tokenize_text("안녕하세요 세계")
        assert len(tokens) == 2
        # Verify round-trip: NFC recomposition recovers the original syllables
        import unicodedata
        assert unicodedata.normalize("NFC", tokens[0]) == "안녕하세요"
        assert unicodedata.normalize("NFC", tokens[1]) == "세계"

    def test_mixed_scripts(self):
        from core.text import tokenize_text
        assert tokenize_text("hello שלום world") == ["hello", "שלום", "world"]

    def test_empty_string(self):
        from core.text import tokenize_text
        assert tokenize_text("") == []

    def test_strip_combining_marks_latin_diacritics(self):
        from core.text import strip_combining_marks
        assert strip_combining_marks("décision") == "decision"

    def test_strip_combining_marks_hebrew_niqud(self):
        from core.text import strip_combining_marks
        assert strip_combining_marks("סִפְרִיָּה") == "ספריה"

    def test_normalize_for_index_mixed_case_and_scripts(self):
        from core.text import normalize_for_index
        assert normalize_for_index("Hello שלום World") == "hello שלום world"


# ---------------------------------------------------------------------------
# TestContentTokensMultilingual — content_tokens with Hebrew
# ---------------------------------------------------------------------------


class TestContentTokensMultilingual:
    """Tests for content_tokens handling of Hebrew stopwords and mixed-script
    text, and verifying that English stemming does not mutate Hebrew tokens."""

    def test_hebrew_stopwords_filtered(self):
        """Hebrew stopwords (של, על) should be filtered, leaving only
        content words."""
        tokens = content_tokens("של על שלום")
        assert "שלום" in tokens
        assert "של" not in tokens
        assert "על" not in tokens

    def test_english_and_hebrew_mixed_stopwords(self):
        """English 'the' should be filtered; Hebrew and English content
        words should survive."""
        tokens = content_tokens("the שלום world")
        assert "שלום" in tokens
        assert "world" in tokens
        assert "the" not in tokens

    def test_plural_stemmer_does_not_touch_hebrew(self):
        """The English plural-stem expansion should not modify Hebrew tokens.
        A Hebrew word like שלומות should remain unchanged (no 'y' suffix, no
        stripping)."""
        tokens = content_tokens("שלומות")
        assert "שלומות" in tokens
        # Ensure no spurious variants were created
        assert all(not t.isascii() for t in tokens)


# ---------------------------------------------------------------------------
# TestScriptsDiffer — cross-language bypass in routing selection
# ---------------------------------------------------------------------------


class TestScriptsDiffer:
    """Tests for _scripts_differ: detects when two token sets use entirely
    different Unicode scripts (Latin vs non-Latin)."""

    def test_hebrew_vs_english(self):
        from semantic.agent_conversation_memory_routing_selection import _scripts_differ
        assert _scripts_differ({"שלום"}, {"hello"}) is True

    def test_hebrew_vs_hebrew(self):
        from semantic.agent_conversation_memory_routing_selection import _scripts_differ
        assert _scripts_differ({"שלום"}, {"עולם"}) is False

    def test_english_vs_english(self):
        from semantic.agent_conversation_memory_routing_selection import _scripts_differ
        assert _scripts_differ({"hello"}, {"world"}) is False

    def test_shared_token_means_no_differ(self):
        """When two sets share at least one token, scripts don't 'differ'
        regardless of other tokens."""
        from semantic.agent_conversation_memory_routing_selection import _scripts_differ
        assert _scripts_differ({"hello"}, {"hello", "שלום"}) is False

    def test_empty_set_a(self):
        from semantic.agent_conversation_memory_routing_selection import _scripts_differ
        assert _scripts_differ(set(), {"hello"}) is False

    def test_empty_set_b(self):
        from semantic.agent_conversation_memory_routing_selection import _scripts_differ
        assert _scripts_differ({"hello"}, set()) is False

    def test_both_empty(self):
        from semantic.agent_conversation_memory_routing_selection import _scripts_differ
        assert _scripts_differ(set(), set()) is False


# ---------------------------------------------------------------------------
# TestTokenizeQueryMultilingual — tokenize_query with multiple scripts
# ---------------------------------------------------------------------------


class TestTokenizeQueryMultilingual:
    """Tests for tokenize_query from retrieval/lexical.py with Hebrew,
    mixed-script input, and plural-stem expansion behavior."""

    def test_hebrew_query_tokens(self):
        tokens = tokenize_query("שלום עולם")
        assert "שלום" in tokens
        assert "עולם" in tokens

    def test_mixed_query_tokens(self):
        tokens = tokenize_query("hello שלום")
        assert "hello" in tokens
        assert "שלום" in tokens

    def test_plural_stemmer_on_english_not_hebrew(self):
        """English 'reservations' should produce a stem variant
        ('reservation'), but Hebrew 'שלום' should have no variants."""
        tokens = tokenize_query("reservations שלום")
        assert "reservations" in tokens
        assert "reservation" in tokens
        assert "שלום" in tokens
        # Verify no spurious Hebrew variants were created
        hebrew_tokens = [t for t in tokens if not t.isascii()]
        assert hebrew_tokens == ["שלום"]
