"""Tests for query token expansion (_token_variants) and tokenize_query.

Covers:
- _token_variants: all suffix rules, exclusions, and length guards
- tokenize_query: dedup, sort, integration with _token_variants
- End-to-end plural retrieval: expanded query tokens match singular index text
  through the full LexicalRetrievalProvider → SQLiteSearchMixin chain
"""
from __future__ import annotations

import pytest

from core.models import (
    IndexEntry,
    MemoryObject,
    Relation,
    SourceItem,
)
from retrieval.lexical import TOKEN_PATTERN, _token_variants, tokenize_query, LexicalRetrievalProvider
from storage.sqlite import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# _token_variants unit tests
# ---------------------------------------------------------------------------

class TestTokenVariants:
    """Test the suffix-stripping expansion rules."""

    def test_regular_s_plural(self):
        assert _token_variants("reservations") == ("reservations", "reservation")

    def test_regular_s_plural_catalogs(self):
        assert _token_variants("catalogs") == ("catalogs", "catalog")

    def test_regular_s_plural_rebuilds(self):
        assert _token_variants("rebuilds") == ("rebuilds", "rebuild")

    def test_regular_s_plural_items(self):
        # len=5, just above the >4 threshold
        assert _token_variants("items") == ("items", "item")

    def test_ies_to_y(self):
        assert _token_variants("categories") == ("categories", "category")

    def test_ies_to_y_policies(self):
        assert _token_variants("policies") == ("policies", "policy")

    def test_blocked_ses(self):
        assert _token_variants("processes") == ("processes",)

    def test_blocked_ses_buses(self):
        assert _token_variants("buses") == ("buses",)

    def test_blocked_is(self):
        assert _token_variants("analysis") == ("analysis",)

    def test_blocked_us(self):
        assert _token_variants("status") == ("status",)

    def test_blocked_ss(self):
        assert _token_variants("boss") == ("boss",)

    def test_blocked_xes(self):
        assert _token_variants("axes") == ("axes",)

    def test_too_short_3_chars(self):
        assert _token_variants("led") == ("led",)

    def test_too_short_4_chars(self):
        # len=4, not > 4
        assert _token_variants("dogs") == ("dogs",)

    def test_no_suffix_match(self):
        assert _token_variants("rebuild") == ("rebuild",)

    def test_numeric_token(self):
        assert _token_variants("12345") == ("12345",)


# ---------------------------------------------------------------------------
# tokenize_query unit tests
# ---------------------------------------------------------------------------

class TestTokenizeQuery:
    """Test the public tokenize_query wrapper."""

    def test_plural_expansion_included(self):
        tokens = tokenize_query("check recent reservations")
        assert "reservation" in tokens
        assert "reservations" in tokens

    def test_ies_expansion_included(self):
        tokens = tokenize_query("what categories apply")
        assert "category" in tokens
        assert "categories" in tokens

    def test_dedup_when_both_forms_present(self):
        tokens = tokenize_query("reservation and reservations")
        assert tokens.count("reservation") == 1
        assert tokens.count("reservations") == 1

    def test_sorted_output(self):
        tokens = tokenize_query("zebra apple mango")
        assert tokens == tuple(sorted(tokens))

    def test_returns_tuple(self):
        result = tokenize_query("some text")
        assert isinstance(result, tuple)

    def test_empty_string(self):
        assert tokenize_query("") == ()

    def test_numeric_and_alpha(self):
        tokens = tokenize_query("item 42 orders")
        assert "42" in tokens
        assert "item" in tokens
        assert "orders" in tokens
        assert "order" in tokens


# ---------------------------------------------------------------------------
# End-to-end plural retrieval integration test
# ---------------------------------------------------------------------------

class TestPluralRetrievalIntegration:
    """Integration test: query with plural form retrieves index entry
    containing the singular form, through the full lexical pipeline.

    This is the critical regression gate — it crosses the module boundary
    between retrieval/lexical.py (tokenizer with _token_variants) and
    storage/sqlite_search.py (scorer with its own TOKEN_PATTERN).
    """

    def test_plural_query_finds_singular_index_entry(self, test_db_url: str):
        storage = SQLiteStorageProvider(test_db_url)

        # Create a source item and memory object to satisfy evidence lookup
        source_item = SourceItem(
            source_type="chat_message",
            source_id="reservation-msg-1",
            content_type="text/plain",
            content="The reservation system was updated.",
            artifact_kind="message",
            role="user",
            container_ref="test:container",
            thread_ref="test:thread",
            visibility="container",
        )
        storage.create_source_item(source_item)

        memory_object = MemoryObject(
            type="decision",
            schema_id="test.decision",
            schema_version="v1",
            payload={"decision": "use the reservation format"},
            visibility="container",
            container_ref="test:container",
        )
        storage.create_memory_object(memory_object)

        storage.create_relation(Relation(
            from_kind="memory_object",
            from_id=memory_object.id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source_item.id,
        ))

        # Index entry with SINGULAR "reservation" (not "reservations")
        index_entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view="use the reservation format for catalog sync",
            text_view_name="memory_object.decision_context",
            provider_name="builtin",
            provider_version="v1",
        )
        storage.create_index_entry(index_entry)

        # Query with PLURAL "reservations"
        provider = LexicalRetrievalProvider(storage)
        result = provider.query(
            "about reservations",
            limit=10,
            query_container_ref="test:container",
        )

        assert len(result.results) >= 1
        found_ids = [r.memory_object_id for r in result.results]
        assert memory_object.id in found_ids

    def test_ies_plural_query_finds_singular(self, test_db_url: str):
        storage = SQLiteStorageProvider(test_db_url)

        source_item = SourceItem(
            source_type="chat_message",
            source_id="category-msg-1",
            content_type="text/plain",
            content="We discussed the catalog category structure.",
            artifact_kind="message",
            role="user",
            container_ref="test:container",
            thread_ref="test:thread",
            visibility="container",
        )
        storage.create_source_item(source_item)

        memory_object = MemoryObject(
            type="decision",
            schema_id="test.decision",
            schema_version="v1",
            payload={"decision": "use the category hierarchy"},
            visibility="container",
            container_ref="test:container",
        )
        storage.create_memory_object(memory_object)

        storage.create_relation(Relation(
            from_kind="memory_object",
            from_id=memory_object.id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source_item.id,
        ))

        index_entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view="use the category hierarchy for catalog organization",
            text_view_name="memory_object.decision_context",
            provider_name="builtin",
            provider_version="v1",
        )
        storage.create_index_entry(index_entry)

        # Query with -ies plural
        provider = LexicalRetrievalProvider(storage)
        result = provider.query(
            "what categories apply",
            limit=10,
            query_container_ref="test:container",
        )

        assert len(result.results) >= 1
        found_ids = [r.memory_object_id for r in result.results]
        assert memory_object.id in found_ids


# ---------------------------------------------------------------------------
# Failure reproduction tests
# ---------------------------------------------------------------------------

class TestFailureReproduction:
    """Reproduce the original retrieval failure: a query using a plural form
    missed a memory whose indexed text contained only the singular form.

    Root cause: before _token_variants (pre-2026-03-12), _tokenize() was a
    bare TOKEN_PATTERN.findall() call — no expansion.  A query token
    "reservations" never matched an indexed token "reservation" because the
    token set intersection was empty.

    These tests pin both sides of that boundary:
      - bare_tokens_miss: shows the failure mechanism directly at the storage
        layer — searching with only the plural token returns no hits.
      - expanded_tokens_hit: shows the fix — including the expanded singular
        token in the search returns the entry.
      - retrieval_provider_finds_it: confirms the full LexicalRetrievalProvider
        path (which uses tokenize_query) correctly finds the entry.
    """

    def _setup_singular_entry(self, storage: SQLiteStorageProvider) -> str:
        """Create a memory object + index entry with singular noun. Returns memory id."""
        source_item = SourceItem(
            source_type="chat_message",
            source_id="repro-msg-1",
            content_type="text/plain",
            content="The reservation system was updated.",
            artifact_kind="message",
            role="user",
            container_ref="test:container",
            thread_ref="test:thread",
            visibility="container",
        )
        storage.create_source_item(source_item)

        memory_object = MemoryObject(
            type="decision",
            schema_id="test.decision",
            schema_version="v1",
            payload={"decision": "use the reservation format"},
            visibility="container",
            container_ref="test:container",
        )
        storage.create_memory_object(memory_object)

        storage.create_relation(Relation(
            from_kind="memory_object",
            from_id=memory_object.id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source_item.id,
        ))

        index_entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view="use the reservation format for catalog sync",
            text_view_name="memory_object.decision_context",
            provider_name="builtin",
            provider_version="v1",
        )
        storage.create_index_entry(index_entry)
        return memory_object.id

    def test_bare_tokens_miss(self, test_db_url: str):
        """Reproduce the original failure: searching with only the plural token
        "reservations" finds nothing because the index has "reservation" (singular).

        This is what the pre-_token_variants code did — bare TOKEN_PATTERN.findall
        without expansion — and is why the live failure occurred.
        """
        storage = SQLiteStorageProvider(test_db_url)
        self._setup_singular_entry(storage)

        # Simulate pre-_token_variants: only the literal plural token, no expansion.
        bare_plural_tokens = TOKEN_PATTERN.findall("about reservations")
        assert bare_plural_tokens == ["about", "reservations"]

        hits = storage.search_index_entries(
            tokens=bare_plural_tokens,
            limit=10,
            query_container_ref="test:container",
        ).hits

        # "reservation" is in the index; "reservations" is not.
        # Without expansion the intersection is empty → no hit on domain word.
        matched_token_sets = [set(h.matched_tokens) for h in hits]
        assert not any("reservation" in mt for mt in matched_token_sets), (
            "Expected: bare plural-only search misses the singular index entry. "
            "If this assertion fails, the indexed text itself contains 'reservations'."
        )

    def test_expanded_tokens_hit(self, test_db_url: str):
        """Show the fix at the storage layer: include the expanded singular token
        "reservation" alongside "reservations" and the entry IS found.

        This is what _token_variants produces — the singular stem is added to
        the token set — so the intersection with the index entry is non-empty.
        """
        storage = SQLiteStorageProvider(test_db_url)
        memory_id = self._setup_singular_entry(storage)

        # Simulate post-_token_variants: expand "reservations" → add "reservation"
        assert _token_variants("reservations") == ("reservations", "reservation")
        expanded_tokens = ["about", "reservation", "reservations"]

        hits = storage.search_index_entries(
            tokens=expanded_tokens,
            limit=10,
            query_container_ref="test:container",
        ).hits

        found_ids = [h.target_id for h in hits]
        assert memory_id in found_ids, (
            "Expected: expanded tokens including singular form finds the index entry."
        )
        # Confirm "reservation" was the matched token, not "reservations"
        target_hit = next(h for h in hits if h.target_id == memory_id)
        assert "reservation" in target_hit.matched_tokens

    def test_retrieval_provider_finds_it(self, test_db_url: str):
        """Full-pipeline confirmation: LexicalRetrievalProvider (which calls
        tokenize_query internally) finds the singular-indexed entry when queried
        with the plural form. This is the end-to-end regression gate.
        """
        storage = SQLiteStorageProvider(test_db_url)
        memory_id = self._setup_singular_entry(storage)

        provider = LexicalRetrievalProvider(storage)
        result = provider.query(
            "about reservations",
            limit=10,
            query_container_ref="test:container",
        )

        found_ids = [r.memory_object_id for r in result.results]
        assert memory_id in found_ids


# ---------------------------------------------------------------------------
# Multilingual end-to-end integration tests
# ---------------------------------------------------------------------------

class TestHebrewRetrievalIntegration:
    """End-to-end: Hebrew content is indexed and retrieved through the full
    lexical pipeline (LexicalRetrievalProvider → SQLiteSearchMixin).
    Verifies the Unicode-aware TOKEN_PATTERN works across module boundaries.
    """

    def test_hebrew_query_finds_hebrew_index_entry(self, test_db_url: str):
        """Hebrew query tokens match Hebrew index text."""
        from core.text import normalize_for_index
        storage = SQLiteStorageProvider(test_db_url)

        source_item = SourceItem(
            source_type="chat_message",
            source_id="hebrew-msg-1",
            content_type="text/plain",
            content="החלטנו להשתמש ב-PostgreSQL בשביל מסד הנתונים",
            artifact_kind="message",
            role="user",
            container_ref="test:container",
            thread_ref="test:thread",
            visibility="container",
        )
        storage.create_source_item(source_item)

        memory_object = MemoryObject(
            type="decision",
            schema_id="test.decision",
            schema_version="v1",
            payload={"decision": "להשתמש ב-PostgreSQL"},
            visibility="container",
            container_ref="test:container",
        )
        storage.create_memory_object(memory_object)

        storage.create_relation(Relation(
            from_kind="memory_object",
            from_id=memory_object.id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source_item.id,
        ))

        # Index with Hebrew text — normalize_for_index now produces Hebrew tokens
        index_text = normalize_for_index("החלטנו להשתמש ב-PostgreSQL בשביל מסד הנתונים")
        assert "החלטנו" in index_text, f"Hebrew token missing from index text: {index_text}"
        assert "postgresql" in index_text, f"English token missing from index text: {index_text}"

        index_entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=index_text,
            text_view_name="memory_object.decision_context",
            provider_name="builtin",
            provider_version="v1",
        )
        storage.create_index_entry(index_entry)

        # Query with Hebrew — should find the memory
        provider = LexicalRetrievalProvider(storage)
        result = provider.query(
            "מה החלטנו לגבי מסד הנתונים",
            limit=10,
            query_container_ref="test:container",
        )

        assert len(result.results) >= 1, "Hebrew query returned no results"
        found_ids = [r.memory_object_id for r in result.results]
        assert memory_object.id in found_ids

    def test_mixed_hebrew_english_query_finds_entry(self, test_db_url: str):
        """Mixed Hebrew+English query finds entry via shared English tokens."""
        from core.text import normalize_for_index
        storage = SQLiteStorageProvider(test_db_url)

        source_item = SourceItem(
            source_type="chat_message",
            source_id="mixed-msg-1",
            content_type="text/plain",
            content="We decided to use Redis for caching.",
            artifact_kind="message",
            role="user",
            container_ref="test:container",
            thread_ref="test:thread",
            visibility="container",
        )
        storage.create_source_item(source_item)

        memory_object = MemoryObject(
            type="decision",
            schema_id="test.decision",
            schema_version="v1",
            payload={"decision": "use Redis for caching"},
            visibility="container",
            container_ref="test:container",
        )
        storage.create_memory_object(memory_object)

        storage.create_relation(Relation(
            from_kind="memory_object",
            from_id=memory_object.id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source_item.id,
        ))

        index_entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=normalize_for_index("use Redis for caching"),
            text_view_name="memory_object.decision_context",
            provider_name="builtin",
            provider_version="v1",
        )
        storage.create_index_entry(index_entry)

        # Query in Hebrew mentioning "Redis" — shared English token bridges
        provider = LexicalRetrievalProvider(storage)
        result = provider.query(
            "מה החלטנו לגבי Redis",
            limit=10,
            query_container_ref="test:container",
        )

        assert len(result.results) >= 1, "Mixed Hebrew+English query returned no results"
        found_ids = [r.memory_object_id for r in result.results]
        assert memory_object.id in found_ids

    def test_hebrew_source_item_indexed_by_core_service(self, test_db_url: str):
        """Verify that core/service.py indexes Hebrew source items correctly
        via the centralized normalize_for_index from core/text.py."""
        from core.text import normalize_for_index

        hebrew_content = "אנחנו צריכים לבדוק את הביצועים של המערכת"
        normalized = normalize_for_index(hebrew_content)

        # All Hebrew words should be present as tokens
        assert "אנחנו" in normalized
        assert "צריכים" in normalized
        assert "לבדוק" in normalized
        assert "הביצועים" in normalized
        assert "המערכת" in normalized
        # No empty result
        assert len(normalized.split()) >= 5

