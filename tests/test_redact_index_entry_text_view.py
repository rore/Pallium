"""Unit tests for ``SqliteStorage.redact_index_entry_text_view`` (PR 0 step 5).

Validates the FTS-safe DELETE+INSERT pattern that keeps lexical
search consistent with the ``index_entries.text_view`` column after
a secret redaction rewrite. The pre-existing
``update_index_entry_text_view`` mutates only the SQLAlchemy record
and leaves the FTS5 mirror table stale — that gap is what motivated
this helper.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from core.indexing import build_index_entry
from core.models import new_id, utc_now
from storage.sqlite import SQLiteStorageProvider


CONTAINER = "git:example.com/index-test"


@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'fts_redact.db'}"


@pytest.fixture
def storage(test_db_url):
    return SQLiteStorageProvider(test_db_url)


def _seed_lexical_entry(storage, *, text_view: str, target_id: str | None = None) -> str:
    """Seed an operational_fact-like lexical index entry.

    Uses a memory_object target so ``_resolve_container_ref_in_session``
    finds a container_ref. Returns the created ``index_entry_id``.
    """
    from storage.sqlite_schema import MemoryObjectRecord

    memory_id = target_id or new_id()
    now = utc_now()
    # Insert a minimal memory_object row so container_ref resolution works.
    with storage._session_factory() as session:
        session.add(
            MemoryObjectRecord(
                id=memory_id,
                type="operational_fact",
                schema_id="agent_work_trace.operational_fact",
                schema_version="1",
                payload_json="{}",
                envelope_json=None,
                lifecycle="active",
                visibility="private",
                container_ref=CONTAINER,
                actor_ref=None,
                freshness_at=now,
                subject="test subject",
                created_at=now,
            )
        )
        session.commit()

    entry = build_index_entry(
        target_kind="memory_object",
        target_id=memory_id,
        index_type="lexical",
        text_view=text_view,
        text_view_name="operational_fact",
    )
    storage.create_index_entry(entry)
    return entry.id


def _fts_rows_for(storage, index_entry_id):
    """Read the lexical_fts virtual table for a given entry."""
    with storage._session_factory() as session:
        rows = session.execute(
            text(
                "SELECT text_view FROM lexical_fts "
                "WHERE index_entry_id = :id"
            ),
            {"id": index_entry_id},
        ).fetchall()
    return [r[0] for r in rows]


class TestRedactIndexEntryTextViewLexical:
    def test_updates_both_index_entries_and_lexical_fts(self, storage):
        entry_id = _seed_lexical_entry(
            storage,
            text_view="please redact my secret_token abc123",
        )
        # Sanity: FTS row currently has the pre-redaction text.
        pre = _fts_rows_for(storage, entry_id)
        assert pre and "secret_token abc123" in pre[0]

        storage.redact_index_entry_text_view(
            entry_id,
            "please redact my [REDACTED-16c]",
        )

        # index_entries.text_view mutated.
        entry = storage.get_index_entry(entry_id)
        assert "abc123" not in entry.text_view
        assert "[REDACTED-16c]" in entry.text_view

        # lexical_fts.text_view mutated (this is the load-bearing test —
        # the pre-existing update_index_entry_text_view leaves this stale).
        post = _fts_rows_for(storage, entry_id)
        assert post, "lexical_fts row was deleted, not replaced"
        assert "abc123" not in post[0]
        assert "[REDACTED-16c]" in post[0]

    def test_idempotent(self, storage):
        entry_id = _seed_lexical_entry(storage, text_view="original")
        storage.redact_index_entry_text_view(entry_id, "redacted-once")
        storage.redact_index_entry_text_view(entry_id, "redacted-once")
        # Exactly one FTS row still exists (not duplicated).
        assert len(_fts_rows_for(storage, entry_id)) == 1

    def test_raises_key_error_on_missing_id(self, storage):
        with pytest.raises(KeyError):
            storage.redact_index_entry_text_view(
                "does-not-exist", "whatever",
            )

    def test_lexical_search_reflects_redaction(self, storage):
        entry_id = _seed_lexical_entry(
            storage,
            text_view="banana banana banana secretword banana",
        )
        # Before redaction: token searchable.
        results = storage.search_index_entries(
            tokens=["secretword"], limit=10,
        )
        assert any(hit.index_entry_id == entry_id for hit in results.hits)

        storage.redact_index_entry_text_view(
            entry_id, "banana banana banana [REDACTED-10c] banana",
        )

        # After redaction: token gone from FTS index.
        results_after = storage.search_index_entries(
            tokens=["secretword"], limit=10,
        )
        assert not any(hit.index_entry_id == entry_id for hit in results_after.hits), (
            "lexical_fts still returns the pre-redaction token — "
            "FTS mirror was not rebuilt"
        )

    def test_pre_existing_update_leaves_fts_stale(self, storage):
        """Regression pin: the OLD method (``update_index_entry_text_view``)
        DOES leave FTS stale. This test locks that behavior so nobody
        silently patches the old method to also update FTS (which would
        change the security posture of unrelated call sites)."""
        entry_id = _seed_lexical_entry(
            storage, text_view="please find secretword here",
        )
        # Use the pre-existing method.
        storage.update_index_entry_text_view(
            entry_id, "please find [REDACTED-10c] here",
        )
        # index_entries.text_view IS updated.
        entry = storage.get_index_entry(entry_id)
        assert "[REDACTED-10c]" in entry.text_view
        # But lexical_fts still holds the pre-redaction text.
        fts = _fts_rows_for(storage, entry_id)
        assert fts and "secretword" in fts[0], (
            "The pre-existing update_index_entry_text_view now updates "
            "FTS too — that changes the security posture. Either revert "
            "or migrate all callers to redact_index_entry_text_view."
        )


class TestRedactIndexEntryTextViewNonLexical:
    def test_vector_index_type_skips_fts_rebuild(self, storage):
        """Non-lexical index entries (vector) have no ``lexical_fts``
        row; the helper must not raise when index_type != 'lexical'."""
        # Build a vector index entry directly against the same target.
        entry_id = _seed_lexical_entry(storage, text_view="ignored")
        # Now build a second entry with index_type='vector' via
        # a follow-up create — but the helper only cares about index_type
        # from the record. Simulate by creating a vector entry manually.
        with storage._session_factory() as session:
            from storage.sqlite_schema import IndexEntryRecord, MemoryObjectRecord

            target = session.query(MemoryObjectRecord).first()
            v_id = new_id()
            session.add(
                IndexEntryRecord(
                    id=v_id,
                    target_kind="memory_object",
                    target_id=target.id,
                    index_type="vector",
                    text_view="vector text with secretword",
                    text_view_name="operational_fact",
                    provider_name="test",
                    provider_version="1",
                )
            )
            session.commit()

        # Call the helper — must succeed even without an FTS row.
        storage.redact_index_entry_text_view(v_id, "redacted vector text")
        entry = storage.get_index_entry(v_id)
        assert "secretword" not in entry.text_view
        # No FTS row was ever created for the vector entry; the DELETE
        # branch of the helper is skipped because index_type != 'lexical'.
