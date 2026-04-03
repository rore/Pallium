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
from retrieval.lexical import _token_variants, tokenize_query, LexicalRetrievalProvider
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
