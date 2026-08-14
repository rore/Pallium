"""Forget-guarantee under mid-query races on the batched retrieval path.

The retrieval path batches source_item reads (one prefetch at the candidate
gate in ``storage/sqlite_search.py``, one at hydration in
``retrieval/lexical.py``) for performance. Those prefetches are point-in-time
SNAPSHOTS, so a source item forgotten/deleted DURING a query could otherwise be
served from stale state. ``LexicalRetrievalProvider`` re-reads the final emitted
source ids ONCE at emission time and drops any that became forgotten/deleted, so
the forget guarantee holds even under a mid-query race. These tests pin that
behaviour.
"""

from __future__ import annotations

from core.models import IndexEntry, SourceItem
from retrieval.lexical import LexicalRetrievalProvider
from storage.sqlite import SQLiteStorageProvider


def _seed_source_item(storage: SQLiteStorageProvider) -> SourceItem:
    item = SourceItem(
        source_type="conversation",
        source_id="race-msg-1",
        content_type="text/plain",
        content="reservation system alpha bravo charlie",
        role="user",
        container_ref="test:container",
        thread_ref="test:thread",
        visibility="container",
    )
    storage.create_source_item(item)
    storage.create_index_entry(
        IndexEntry(
            target_kind="source_item",
            target_id=item.id,
            index_type="lexical",
            text_view=item.content,
        )
    )
    return item


def test_source_item_retrievable_before_forget(test_db_url: str) -> None:
    """Sanity: the seeded item is returned by the lexical path when live."""
    storage = SQLiteStorageProvider(test_db_url)
    item = _seed_source_item(storage)
    provider = LexicalRetrievalProvider(storage)

    result = provider.query("reservation", limit=5, query_container_ref="test:container")

    returned = [r.source_item_id for r in result.results if r.result_kind == "source_hit"]
    assert item.id in returned


def test_forget_landing_mid_query_is_not_emitted(test_db_url: str) -> None:
    """A forget that commits AFTER the candidate/hydration snapshot but BEFORE
    emission must not leak: the emission-time revalidation re-reads the final
    ids and drops the now-forgotten item.

    Deterministic race hook: wrap ``get_source_items`` so the FIRST call (the
    candidate-gate prefetch) returns the pre-forget snapshot (item still live,
    so it passes the forgotten gate) and, as a side effect, commits the forget.
    Every later call in the same query (hydration + the emission-time
    revalidation) then reads the forgotten row. Without the revalidation the
    item would be emitted (gate passed on the stale snapshot, hydration does not
    re-check forgotten); with it, the item is dropped.
    """
    storage = SQLiteStorageProvider(test_db_url)
    item = _seed_source_item(storage)
    provider = LexicalRetrievalProvider(storage)

    real_get_source_items = storage.get_source_items
    state = {"raced": False}

    def racing_get_source_items(ids):
        snapshot = real_get_source_items(ids)
        if not state["raced"] and item.id in snapshot:
            # Forget commits mid-query, after this snapshot was taken.
            storage.forget_source_item(item.id, reason="mid-query race")
            state["raced"] = True
        return snapshot

    storage.get_source_items = racing_get_source_items  # type: ignore[method-assign]

    result = provider.query("reservation", limit=5, query_container_ref="test:container")

    returned = [r.source_item_id for r in result.results if r.result_kind == "source_hit"]
    assert state["raced"], "the race hook never fired (query did not reach the gate prefetch)"
    assert item.id not in returned, "a source item forgotten mid-query was emitted"
