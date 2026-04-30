"""End-to-end test for the evidence drill-down feature.

Full pipeline: ingest → process → query → verify memory_object_id in
injectable blocks → GET /memory/{id}/evidence → verify source content.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig


def _config(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )


class TestEvidenceDrilldownE2E:
    """Full pipeline test: ingest → process → query → evidence drill-down."""

    def test_ingest_query_and_drill_down(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service

        with TestClient(app) as client:
            # 1. Ingest a message that triggers decision extraction
            ingest_response = client.post("/items", json=[{
                "source_type": "chat_message",
                "source_id": "e2e-decision-1",
                "content_type": "text/plain",
                "content": "We decided to use PostgreSQL for the analytics pipeline because of low latency requirements and the need for complex joins across multiple event tables",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "e2e:container:test",
                "thread_ref": "e2e:thread:test",
                "visibility": "private",
            }])
            assert ingest_response.status_code == 200

            # 2. Process the queue (creates memory objects + relations)
            service.drain_processing_queue(worker_id="e2e-worker")

            # 3. Query — use the debug endpoint to see all results regardless of injection
            query_response = client.post("/query/debug", json={
                "text": "We decided to use PostgreSQL for the analytics pipeline",
                "container_ref": "e2e:container:test",
                "visibility": "private",
            })
            assert query_response.status_code == 200
            query_body = query_response.json()

            # 4. Find a memory hit result with memory_object_id
            results = query_body["results"]
            memory_hit = None
            for r in results:
                if r.get("result_kind") == "memory_hit" and r.get("memory_object_id"):
                    memory_hit = r
                    break
            assert memory_hit is not None, f"No memory_hit with memory_object_id found. Results: {results}"
            memory_object_id = memory_hit["memory_object_id"]

            # 5. Verify injectable blocks also carry memory_object_id
            blocks = query_body.get("injectable_blocks", [])
            block_mo_ids = [b.get("memory_object_id") for b in blocks if b.get("memory_object_id")]
            # Blocks may or may not be populated depending on injection decision,
            # but if they are, they should have the ID
            if blocks:
                assert any(mo_id is not None for mo_id in block_mo_ids), (
                    f"Injectable blocks present but none have memory_object_id: {blocks}"
                )

            # 6. Drill down: GET /memory/{id}/evidence
            evidence_response = client.get(
                f"/memory/{memory_object_id}/evidence",
                params={"container_ref": "e2e:container:test"},
            )
            assert evidence_response.status_code == 200
            evidence_body = evidence_response.json()

            assert evidence_body["memory_object_id"] == memory_object_id
            assert len(evidence_body["items"]) > 0

            # 7. Verify the source content is the original message
            source_contents = [item["content"] for item in evidence_body["items"]]
            assert any("PostgreSQL" in c for c in source_contents), (
                f"Expected PostgreSQL in evidence content, got: {source_contents}"
            )

            # 8. Verify cross-container access is blocked
            cross_response = client.get(
                f"/memory/{memory_object_id}/evidence",
                params={"container_ref": "e2e:container:other-user"},
            )
            assert cross_response.status_code == 404

    def test_multiple_messages_single_thread_drilldown(self, test_db_url: str) -> None:
        """Multiple messages in a thread → query → drill down to all evidence."""
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service

        messages = [
            "We decided to use Redis for the cache layer",
            "The team agreed that Redis Cluster gives us the HA we need",
            "Investigation found that Memcached doesn't support persistence",
        ]

        with TestClient(app) as client:
            for i, msg in enumerate(messages):
                client.post("/items", json=[{
                    "source_type": "chat_message",
                    "source_id": f"e2e-multi-{i}",
                    "content_type": "text/plain",
                    "content": msg,
                    "artifact_kind": "message",
                    "role": "user",
                    "container_ref": "e2e:container:multi",
                    "thread_ref": "e2e:thread:multi",
                    "visibility": "private",
                }])
                service.drain_processing_queue(worker_id="e2e-worker")

            # Query for Redis-related memories
            query_response = client.post("/query", json={
                "text": "Redis cache",
                "container_ref": "e2e:container:multi",
                "visibility": "private",
                "limit": 10,
            })
            assert query_response.status_code == 200
            blocks = query_response.json()["injectable_blocks"]

            # Drill down on each block that has a memory_object_id
            for block in blocks:
                mo_id = block.get("memory_object_id")
                if not mo_id:
                    continue
                ev = client.get(
                    f"/memory/{mo_id}/evidence",
                    params={"container_ref": "e2e:container:multi"},
                )
                assert ev.status_code == 200
                items = ev.json()["items"]
                assert len(items) > 0
                # Every evidence item should have content
                for item in items:
                    assert item["content"], f"Evidence item has empty content: {item}"
