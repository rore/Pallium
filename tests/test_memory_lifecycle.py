from __future__ import annotations

from core.service import PalliumService
from retrieval.lexical import LexicalRetrievalProvider
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


def test_superseded_memory_is_hidden_but_evidence_remains(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    retrieval = LexicalRetrievalProvider(storage)
    service = PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins={"demo_agent_memory": DemoAgentMemoryPlugin()},
        default_use_case="demo_agent_memory",
    )

    old_result = service.ingest_item(
        source_type="decision_note",
        source_id="decision-old",
        content_type="text/plain",
        content="Decision: use arrival time for reservation ordering across all background worker processes to keep the ingestion pipeline simple and predictable.",
        metadata={"topic": "reservation ordering"},
        use_case=None,
        artifact_kind="message",
        role="user",
        thread_ref="thread-1",
    )
    service.drain_processing_queue(worker_id="memory-lifecycle")
    old_processing = service.get_item_processing(old_result.source_item_id)

    new_result = service.ingest_item(
        source_type="decision_note",
        source_id="decision-new",
        content_type="text/plain",
        content="Decision: use item event time for reservation ordering instead of arrival time to avoid missed hold updates during concurrent sync delay operations.",
        metadata={"topic": "reservation ordering"},
        use_case=None,
        artifact_kind="message",
        role="user",
        thread_ref="thread-1",
    )

    service.drain_processing_queue(worker_id="memory-lifecycle")
    new_processing = service.get_item_processing(new_result.source_item_id)

    old_memory_id = old_processing.memory_object_ids[0]
    new_memory_id = new_processing.memory_object_ids[0]
    service.supersede_memory_object(old_memory_id, new_memory_id)

    query_result = service.query("reservation ordering reservation ordering", limit=10, thread_ref="thread-1")
    memory_hits = [item for item in query_result.results if item.result_kind == "memory_hit"]
    source_hits = [item for item in query_result.results if item.result_kind == "source_hit"]

    assert all(item.memory_object_id != old_memory_id for item in memory_hits)
    assert any(item.memory_object_id == new_memory_id for item in memory_hits)
    assert any(item.source_id == "decision-old" for item in source_hits)
    assert storage.get_memory_object(old_memory_id).lifecycle == "superseded"
    assert storage.get_memory_object(new_memory_id).lifecycle == "active"
