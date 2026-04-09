"""Tests for index entry retargeting during memory supersession.

Covers:
- Storage-level retarget_index_entries_for_target (lexical + vector entries)
- Consolidation runner cross-type supersession (atomic_fact → fact_summary)
- Consolidation runner same-type supersession (fact_summary v1 → v2)
- Atomic commit path supersession (_apply_supersession_pairs_in_session)
- Chain retargeting (entries follow through multiple supersession levels)
- No-op when target has no entries
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text as sa_text

from core.models import (
    IndexEntry,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    MemorySubjectAnchor,
    Relation,
    SourceItem,
    new_id,
)
from storage.sqlite import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source_item(container_ref: str = "container-1") -> SourceItem:
    return SourceItem(
        source_type="chat_thread",
        source_id=f"thread-{new_id()[:8]}",
        content_type="text/plain",
        content="Test source item content for retargeting tests.",
        metadata={},
        artifact_kind="message",
        role="user",
        container_ref=container_ref,
        thread_ref="thread-a",
        visibility="container",
    )


def _make_memory_object(
    memory_type: str = "atomic_fact",
    container_ref: str = "container-1",
    subject: str = "Caroline",
    payload: dict | None = None,
) -> MemoryObject:
    return MemoryObject(
        type=memory_type,
        schema_id=f"conversational_knowledge.{memory_type}",
        schema_version="v1",
        payload=payload or {"subject": subject, "statement": f"test fact about {subject}"},
        visibility="container",
        container_ref=container_ref,
        envelope=MemoryEnvelope(
            schema_id="core.memory_envelope",
            schema_version="v1",
            kind="fact",
            scope=MemoryEnvelopeScope(container_ref=container_ref, thread_ref="thread-a"),
            subjects=[MemorySubjectAnchor(kind="entity", value=subject)],
            confidence="high",
            derivation=MemoryEnvelopeDerivation(
                producer_kind="item_extraction",
                producer_schema_id="conversational_knowledge",
                producer_schema_version="v1",
                prompt_variant="default",
                model_role="write_time_extraction",
                kind_basis="llm_subject_hints",
            ),
        ),
    )


def _make_index_entry(
    target_kind: str,
    target_id: str,
    index_type: str = "lexical",
    text_view: str = "test content for index entry",
    text_view_name: str = "memory_object.fact_statement",
) -> IndexEntry:
    return IndexEntry(
        target_kind=target_kind,
        target_id=target_id,
        index_type=index_type,
        text_view=text_view,
        text_view_name=text_view_name,
    )


def _fts5_target_ids(engine, index_entry_id: str) -> list[str]:
    """Read target_id from FTS5 for a given index_entry_id."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT target_id FROM lexical_fts WHERE index_entry_id = :id"),
            {"id": index_entry_id},
        ).fetchall()
    return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# Storage-level retarget tests
# ---------------------------------------------------------------------------

class TestRetargetIndexEntries:

    def test_retargets_lexical_entry(self, test_db_url: str) -> None:
        storage = SQLiteStorageProvider(test_db_url)
        engine = create_engine(test_db_url)
        old_mo = _make_memory_object(memory_type="atomic_fact")
        new_mo = _make_memory_object(memory_type="fact_summary")
        storage.create_memory_object(old_mo)
        storage.create_memory_object(new_mo)

        entry = _make_index_entry("memory_object", old_mo.id, "lexical", "caroline received a necklace")
        storage.create_index_entry(entry)

        # Verify entry points to old target
        assert storage.get_index_entry(entry.id).target_id == old_mo.id
        assert _fts5_target_ids(engine, entry.id) == [old_mo.id]

        # Retarget
        count = storage.retarget_index_entries_for_target("memory_object", old_mo.id, new_mo.id)
        assert count == 1

        # Verify entry now points to new target
        assert storage.get_index_entry(entry.id).target_id == new_mo.id
        assert _fts5_target_ids(engine, entry.id) == [new_mo.id]

    def test_retargets_vector_entry(self, test_db_url: str) -> None:
        storage = SQLiteStorageProvider(test_db_url)
        old_mo = _make_memory_object(memory_type="atomic_fact")
        new_mo = _make_memory_object(memory_type="fact_summary")
        storage.create_memory_object(old_mo)
        storage.create_memory_object(new_mo)

        entry = _make_index_entry(
            "memory_object", old_mo.id, "vector",
            text_view="Caroline: Caroline received a necklace",
            text_view_name="memory_object.fact_embedding",
        )
        storage.create_index_entry(entry)

        count = storage.retarget_index_entries_for_target("memory_object", old_mo.id, new_mo.id)
        assert count == 1
        assert storage.get_index_entry(entry.id).target_id == new_mo.id

    def test_retargets_multiple_entries(self, test_db_url: str) -> None:
        storage = SQLiteStorageProvider(test_db_url)
        old_mo = _make_memory_object(memory_type="atomic_fact")
        new_mo = _make_memory_object(memory_type="fact_summary")
        storage.create_memory_object(old_mo)
        storage.create_memory_object(new_mo)

        lex_entry = _make_index_entry("memory_object", old_mo.id, "lexical", "necklace fact")
        vec_entry = _make_index_entry(
            "memory_object", old_mo.id, "vector",
            text_view="Caroline: necklace",
            text_view_name="memory_object.fact_embedding",
        )
        storage.create_index_entry(lex_entry)
        storage.create_index_entry(vec_entry)

        count = storage.retarget_index_entries_for_target("memory_object", old_mo.id, new_mo.id)
        assert count == 2
        assert storage.get_index_entry(lex_entry.id).target_id == new_mo.id
        assert storage.get_index_entry(vec_entry.id).target_id == new_mo.id

    def test_noop_when_no_entries(self, test_db_url: str) -> None:
        storage = SQLiteStorageProvider(test_db_url)
        count = storage.retarget_index_entries_for_target("memory_object", "nonexistent", "also-nonexistent")
        assert count == 0

    def test_does_not_retarget_other_targets(self, test_db_url: str) -> None:
        storage = SQLiteStorageProvider(test_db_url)
        mo_a = _make_memory_object(memory_type="atomic_fact", subject="Alice")
        mo_b = _make_memory_object(memory_type="atomic_fact", subject="Bob")
        new_mo = _make_memory_object(memory_type="fact_summary")
        storage.create_memory_object(mo_a)
        storage.create_memory_object(mo_b)
        storage.create_memory_object(new_mo)

        entry_a = _make_index_entry("memory_object", mo_a.id, "lexical", "alice fact")
        entry_b = _make_index_entry("memory_object", mo_b.id, "lexical", "bob fact")
        storage.create_index_entry(entry_a)
        storage.create_index_entry(entry_b)

        storage.retarget_index_entries_for_target("memory_object", mo_a.id, new_mo.id)

        # A's entry retargeted, B's entry unchanged
        assert storage.get_index_entry(entry_a.id).target_id == new_mo.id
        assert storage.get_index_entry(entry_b.id).target_id == mo_b.id

    def test_fts5_text_view_preserved_after_retarget(self, test_db_url: str) -> None:
        """The focused text from the original atomic_fact must survive retargeting."""
        storage = SQLiteStorageProvider(test_db_url)
        engine = create_engine(test_db_url)
        old_mo = _make_memory_object(memory_type="atomic_fact")
        new_mo = _make_memory_object(memory_type="fact_summary")
        storage.create_memory_object(old_mo)
        storage.create_memory_object(new_mo)

        original_text = "caroline received a necklace from her grandma in sweden"
        entry = _make_index_entry("memory_object", old_mo.id, "lexical", original_text)
        storage.create_index_entry(entry)

        storage.retarget_index_entries_for_target("memory_object", old_mo.id, new_mo.id)

        # Text view preserved in storage
        retargeted = storage.get_index_entry(entry.id)
        assert retargeted.text_view == original_text

        # FTS5 text view preserved (searchable)
        with engine.connect() as conn:
            rows = conn.execute(
                sa_text("SELECT text_view FROM lexical_fts WHERE index_entry_id = :id"),
                {"id": entry.id},
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == original_text

    def test_chain_retarget(self, test_db_url: str) -> None:
        """Entries follow through multiple supersession levels: A→B→C."""
        storage = SQLiteStorageProvider(test_db_url)
        mo_a = _make_memory_object(memory_type="atomic_fact", subject="chain-A")
        mo_b = _make_memory_object(memory_type="fact_summary", subject="chain-B")
        mo_c = _make_memory_object(memory_type="fact_summary", subject="chain-C")
        storage.create_memory_object(mo_a)
        storage.create_memory_object(mo_b)
        storage.create_memory_object(mo_c)

        entry = _make_index_entry("memory_object", mo_a.id, "lexical", "focused fact text")
        storage.create_index_entry(entry)

        # A superseded by B
        storage.retarget_index_entries_for_target("memory_object", mo_a.id, mo_b.id)
        assert storage.get_index_entry(entry.id).target_id == mo_b.id

        # B superseded by C
        storage.retarget_index_entries_for_target("memory_object", mo_b.id, mo_c.id)
        assert storage.get_index_entry(entry.id).target_id == mo_c.id

    def test_fts5_searchable_after_retarget(self, test_db_url: str) -> None:
        """After retargeting, FTS5 MATCH still finds the entry with new target_id."""
        storage = SQLiteStorageProvider(test_db_url)
        engine = create_engine(test_db_url)
        old_mo = _make_memory_object(memory_type="atomic_fact")
        new_mo = _make_memory_object(memory_type="fact_summary")
        storage.create_memory_object(old_mo)
        storage.create_memory_object(new_mo)

        entry = _make_index_entry("memory_object", old_mo.id, "lexical", "necklace grandma sweden")
        storage.create_index_entry(entry)

        storage.retarget_index_entries_for_target("memory_object", old_mo.id, new_mo.id)

        # FTS5 search should find the entry
        with engine.connect() as conn:
            rows = conn.execute(
                sa_text(
                    "SELECT target_id, index_entry_id FROM lexical_fts "
                    "WHERE lexical_fts MATCH '\"necklace\"' LIMIT 10"
                ),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == new_mo.id
        assert rows[0][1] == entry.id

    def test_list_index_entries_for_target_reflects_retarget(self, test_db_url: str) -> None:
        """list_index_entries_for_target returns entries under the new target."""
        storage = SQLiteStorageProvider(test_db_url)
        old_mo = _make_memory_object(memory_type="atomic_fact")
        new_mo = _make_memory_object(memory_type="fact_summary")
        storage.create_memory_object(old_mo)
        storage.create_memory_object(new_mo)

        entry = _make_index_entry("memory_object", old_mo.id, "lexical", "retarget list check")
        storage.create_index_entry(entry)

        storage.retarget_index_entries_for_target("memory_object", old_mo.id, new_mo.id)

        # Old target has no entries; new target has the retargeted entry
        assert storage.list_index_entries_for_target("memory_object", old_mo.id) == []
        entries = storage.list_index_entries_for_target("memory_object", new_mo.id)
        assert len(entries) == 1
        assert entries[0].id == entry.id


# ---------------------------------------------------------------------------
# Atomic commit path (thread rebuild supersession)
# ---------------------------------------------------------------------------

class TestAtomicCommitRetarget:

    def test_supersession_pairs_retarget_entries(self, test_db_url: str) -> None:
        """_apply_supersession_pairs_in_session retargets index entries."""
        storage = SQLiteStorageProvider(test_db_url)
        # Create two same-type memories with entries
        old_ts = _make_memory_object(memory_type="thread_summary", subject="summary-old")
        new_ts = _make_memory_object(memory_type="thread_summary", subject="summary-new")
        storage.create_memory_object(old_ts)
        storage.create_memory_object(new_ts)

        entry = _make_index_entry(
            "memory_object", old_ts.id, "lexical",
            text_view="discussion about reservation ordering",
            text_view_name="memory_object.summary",
        )
        storage.create_index_entry(entry)

        # Use commit_process_result with supersession pairs
        from core.contracts import ProcessResult
        result = ProcessResult(
            memory_objects=[],
            relations=[],
            index_entries=[],
        )
        storage.commit_process_result(result=result, supersession_pairs=[(old_ts.id, new_ts.id)])

        # Entry should be retargeted
        assert storage.get_index_entry(entry.id).target_id == new_ts.id
        assert storage.get_memory_object(old_ts.id).lifecycle == "superseded"

    def test_already_superseded_skips_retarget(self, test_db_url: str) -> None:
        """If memory is already superseded, no retarget happens."""
        storage = SQLiteStorageProvider(test_db_url)
        old_ts = _make_memory_object(memory_type="thread_summary")
        new_ts = _make_memory_object(memory_type="thread_summary")
        storage.create_memory_object(old_ts)
        storage.create_memory_object(new_ts)

        # Pre-supersede
        storage.update_memory_object_lifecycle(old_ts.id, "superseded")

        entry = _make_index_entry("memory_object", old_ts.id, "lexical", "already superseded text")
        storage.create_index_entry(entry)

        from core.contracts import ProcessResult
        result = ProcessResult(memory_objects=[], relations=[], index_entries=[])
        storage.commit_process_result(result=result, supersession_pairs=[(old_ts.id, new_ts.id)])

        # Entry stays at old target (supersession was skipped)
        assert storage.get_index_entry(entry.id).target_id == old_ts.id


# ---------------------------------------------------------------------------
# Retention interaction — retargeted entries survive cascade delete of superseded
# ---------------------------------------------------------------------------

class TestRetentionInteraction:

    def test_retention_of_superseded_does_not_delete_retargeted_entries(self, test_db_url: str) -> None:
        """When retention deletes a superseded memory, entries that were retargeted
        to the replacement should NOT be affected."""
        storage = SQLiteStorageProvider(test_db_url)
        source = _make_source_item()
        storage.create_source_item(source)

        old_mo = _make_memory_object(memory_type="atomic_fact")
        new_mo = _make_memory_object(memory_type="fact_summary")
        storage.create_memory_object(old_mo)
        storage.create_memory_object(new_mo)

        # Create relation so new_mo has evidence support
        storage.create_relation(Relation(
            from_kind="memory_object", from_id=new_mo.id,
            relation_type="supported_by",
            to_kind="source_item", to_id=source.id,
        ))

        entry = _make_index_entry("memory_object", old_mo.id, "lexical", "focused fact")
        storage.create_index_entry(entry)

        # Supersede + retarget
        storage.update_memory_object_lifecycle(old_mo.id, "superseded")
        storage.retarget_index_entries_for_target("memory_object", old_mo.id, new_mo.id)

        # Entry now points to new_mo
        assert storage.get_index_entry(entry.id).target_id == new_mo.id

        # Run retention — it should delete old_mo but entry is safe (points to new_mo)
        from core.models import utc_now
        stats = storage.run_retention_pass(
            now=utc_now(),
            batch_size=100,
        )

        # Entry still exists and points to new_mo
        assert storage.get_index_entry(entry.id).target_id == new_mo.id


# ---------------------------------------------------------------------------
# Integration: consolidation runner retargets entries end-to-end
# ---------------------------------------------------------------------------

class TestConsolidationRunnerRetargets:

    def test_cross_type_supersession_retargets_entries(self, test_db_url: str) -> None:
        """Full consolidation: atomic_facts with index entries → fact_summary.
        Entries should be retargeted from superseded atomic_facts to new fact_summary."""
        import json
        from providers.llm.base import LLMProvider, LLMJsonResponse
        from semantic.conversational_knowledge import ConversationalKnowledgePlugin
        from retrieval.lexical import LexicalRetrievalProvider
        from core.service import PalliumService

        class StubProvider(LLMProvider):
            provider_name = "stub"
            def generate_json(self, *, system_prompt, user_prompt, schema_description):
                result = {
                    "summary": "Alice is a citizen of India and speaks Hindi fluently",
                    "superseded_indices": [],
                    "reasoning": "stub",
                }
                return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)

        storage = SQLiteStorageProvider(test_db_url)
        plugin = ConversationalKnowledgePlugin(provider=StubProvider())
        service = PalliumService(
            storage=storage,
            retrieval=LexicalRetrievalProvider(storage),
            semantic_plugins={"conversational_knowledge": plugin},
            default_use_case="conversational_knowledge",
        )

        # Create 3 atomic_facts with index entries (simulating what semantic processing does)
        atomic_ids = []
        entry_ids = []
        for i in range(3):
            mo = MemoryObject(
                type="atomic_fact",
                schema_id="conversational_knowledge.atomic_fact",
                schema_version="v1",
                payload={
                    "subject": "Alice",
                    "statement": f"Alice fact {i}",
                    "category": "personal",
                    "thread_ref": f"t{i}",
                },
                lifecycle="active",
                visibility="public",
                container_ref="c1",
            )
            storage.create_memory_object(mo)
            atomic_ids.append(mo.id)

            # Create lexical + vector entries (like semantic processing does)
            lex_entry = _make_index_entry(
                "memory_object", mo.id, "lexical",
                text_view=f"alice fact {i}",
                text_view_name="memory_object.fact_statement",
            )
            vec_entry = _make_index_entry(
                "memory_object", mo.id, "vector",
                text_view=f"Alice: Alice fact {i}",
                text_view_name="memory_object.fact_embedding",
            )
            storage.create_index_entry(lex_entry)
            storage.create_index_entry(vec_entry)
            entry_ids.extend([lex_entry.id, vec_entry.id])

        # Run consolidation
        result = service.run_consolidation_pass(use_case="conversational_knowledge")
        assert result is not None
        assert len(result.groups) == 1

        # Verify atomic_facts are superseded
        for aid in atomic_ids:
            assert storage.get_memory_object(aid).lifecycle == "superseded"

        # Find the new fact_summary
        summaries = storage.list_memory_objects(memory_types=["fact_summary"], lifecycle="active")
        assert len(summaries) == 1
        fact_summary_id = summaries[0].id

        # KEY ASSERTION: all 6 entries (3 lexical + 3 vector) should now point to fact_summary
        for eid in entry_ids:
            entry = storage.get_index_entry(eid)
            assert entry.target_id == fact_summary_id, (
                f"Entry {eid} still points to {entry.target_id}, expected {fact_summary_id}"
            )

        # Old atomic_facts should have NO entries pointing at them
        for aid in atomic_ids:
            assert storage.list_index_entries_for_target("memory_object", aid) == []

        # fact_summary should have the retargeted entries PLUS its own entries
        all_entries = storage.list_index_entries_for_target("memory_object", fact_summary_id)
        retargeted = [e for e in all_entries if e.id in entry_ids]
        own = [e for e in all_entries if e.id not in entry_ids]
        assert len(retargeted) == 6  # 3 lexical + 3 vector from atomic_facts
        assert len(own) >= 1  # fact_summary's own entries

    def test_same_type_supersession_retargets_entries(self, test_db_url: str) -> None:
        """When fact_summary v2 supersedes v1, v1's entries (including those
        retargeted from atomic_facts) should move to v2."""
        import json
        from providers.llm.base import LLMProvider, LLMJsonResponse
        from semantic.conversational_knowledge import ConversationalKnowledgePlugin
        from retrieval.lexical import LexicalRetrievalProvider
        from core.service import PalliumService

        call_count = 0

        class StubConsolidationProvider(LLMProvider):
            provider_name = "stub"
            def generate_json(self, *, system_prompt, user_prompt, schema_description):
                nonlocal call_count
                call_count += 1
                summary = f"Alice consolidated summary version {call_count}"
                result = {
                    "summary": summary,
                    "superseded_indices": [],
                    "reasoning": "stub",
                }
                return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)

        storage = SQLiteStorageProvider(test_db_url)
        plugin = ConversationalKnowledgePlugin(provider=StubConsolidationProvider())
        service = PalliumService(
            storage=storage,
            retrieval=LexicalRetrievalProvider(storage),
            semantic_plugins={"conversational_knowledge": plugin},
            default_use_case="conversational_knowledge",
        )

        # Create 3 atomic_facts with entries
        original_entry_ids = []
        for i in range(3):
            mo = MemoryObject(
                type="atomic_fact",
                schema_id="conversational_knowledge.atomic_fact",
                schema_version="v1",
                payload={
                    "subject": "Alice", "statement": f"Alice fact {i}",
                    "category": "personal", "thread_ref": f"t{i}",
                },
                lifecycle="active", visibility="public", container_ref="c1",
            )
            storage.create_memory_object(mo)
            entry = _make_index_entry(
                "memory_object", mo.id, "lexical",
                text_view=f"alice fact {i}",
            )
            storage.create_index_entry(entry)
            original_entry_ids.append(entry.id)

        # First consolidation: atomic_facts → fact_summary v1
        result1 = service.run_consolidation_pass(use_case="conversational_knowledge")
        assert result1 is not None
        v1_summaries = storage.list_memory_objects(memory_types=["fact_summary"], lifecycle="active")
        assert len(v1_summaries) == 1
        v1_id = v1_summaries[0].id

        # All original entries point to v1
        for eid in original_entry_ids:
            assert storage.get_index_entry(eid).target_id == v1_id

        # Add new atomic_facts from different threads to trigger re-consolidation
        # (strategy requires MIN_DISTINCT_THREADS=2 and MIN_GROUP_SIZE=2)
        new_entry_ids = []
        for i, tref in enumerate(["t_new1", "t_new2"]):
            new_mo = MemoryObject(
                type="atomic_fact",
                schema_id="conversational_knowledge.atomic_fact",
                schema_version="v1",
                payload={
                    "subject": "Alice", "statement": f"Alice fact new {i}",
                    "category": "personal", "thread_ref": tref,
                },
                lifecycle="active", visibility="public", container_ref="c1",
            )
            storage.create_memory_object(new_mo)
            new_entry = _make_index_entry(
                "memory_object", new_mo.id, "lexical",
                text_view=f"alice fact new {i}",
            )
            storage.create_index_entry(new_entry)
            new_entry_ids.append(new_entry.id)

        # Second consolidation: fact_summary v1 + new atomic_facts → fact_summary v2
        result2 = service.run_consolidation_pass(use_case="conversational_knowledge")
        assert result2 is not None

        # v1 should be superseded
        assert storage.get_memory_object(v1_id).lifecycle == "superseded"

        # Find v2
        v2_summaries = storage.list_memory_objects(memory_types=["fact_summary"], lifecycle="active")
        assert len(v2_summaries) == 1
        v2_id = v2_summaries[0].id
        assert v2_id != v1_id

        # KEY: original entries from atomic_facts should now point to v2 (chain retarget)
        for eid in original_entry_ids:
            entry = storage.get_index_entry(eid)
            assert entry.target_id == v2_id, (
                f"Entry {eid} points to {entry.target_id}, expected v2={v2_id}"
            )

        # New atomic_facts' entries should also point to v2
        for eid in new_entry_ids:
            assert storage.get_index_entry(eid).target_id == v2_id

        # No ghost entries: v1 should have no entries pointing at it
        assert storage.list_index_entries_for_target("memory_object", v1_id) == []

    def test_zero_ghost_entries_after_consolidation(self, test_db_url: str) -> None:
        """After consolidation, NO index entries should point to superseded memories."""
        import json
        from providers.llm.base import LLMProvider, LLMJsonResponse
        from semantic.conversational_knowledge import ConversationalKnowledgePlugin
        from retrieval.lexical import LexicalRetrievalProvider
        from core.service import PalliumService

        class StubProvider(LLMProvider):
            provider_name = "stub"
            def generate_json(self, *, system_prompt, user_prompt, schema_description):
                result = {
                    "summary": "All facts about Alice consolidated",
                    "superseded_indices": [],
                    "reasoning": "stub",
                }
                return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)

        storage = SQLiteStorageProvider(test_db_url)
        service = PalliumService(
            storage=storage,
            retrieval=LexicalRetrievalProvider(storage),
            semantic_plugins={
                "conversational_knowledge": ConversationalKnowledgePlugin(
                    provider=StubProvider(),
                ),
            },
            default_use_case="conversational_knowledge",
        )

        # Create atomic_facts with entries
        for i in range(5):
            mo = MemoryObject(
                type="atomic_fact",
                schema_id="conversational_knowledge.atomic_fact",
                schema_version="v1",
                payload={
                    "subject": "Alice", "statement": f"fact {i}",
                    "category": "personal", "thread_ref": f"t{i}",
                },
                lifecycle="active", visibility="public", container_ref="c1",
            )
            storage.create_memory_object(mo)
            for idx_type, view_name in [
                ("lexical", "memory_object.fact_statement"),
                ("vector", "memory_object.fact_embedding"),
            ]:
                storage.create_index_entry(_make_index_entry(
                    "memory_object", mo.id, idx_type,
                    text_view=f"alice fact {i}",
                    text_view_name=view_name,
                ))

        # Run consolidation
        service.run_consolidation_pass(use_case="conversational_knowledge")

        # THE INVARIANT: zero ghost entries
        all_entries = (
            storage.list_index_entries_by_type("lexical")
            + storage.list_index_entries_by_type("vector")
        )
        ghosts = []
        for entry in all_entries:
            if entry.target_kind != "memory_object":
                continue
            try:
                mo = storage.get_memory_object(entry.target_id)
                if mo.lifecycle == "superseded":
                    ghosts.append((entry.id, entry.target_id, mo.type))
            except KeyError:
                ghosts.append((entry.id, entry.target_id, "MISSING"))

        assert ghosts == [], f"Found {len(ghosts)} ghost entries: {ghosts[:5]}"
