"""Reproduction test: standalone messages in a container produce no atomic_facts.

Simulates real Slack DM patterns where top-level messages each have their own
thread_ref.  In Slack, only explicit thread replies share a parent's thread_ref.
This means most DM channel messages are singleton threads that fall below the
2-item extraction minimum.

Three realistic scenarios based on actual Pelican integration data:

1. Standalone user messages — each top-level DM message has its own thread_ref.
   No assistant messages share these thread_refs (assistant responses route to
   different threads in Pelican's model).  Despite substantive content, no facts
   are extracted because each thread has only 1 item.

2. Mixed container — the same DM channel has a working multi-item thread
   (users replying in-thread) alongside standalone top-level messages.  The
   thread produces facts normally; the standalone messages are silently dropped.
   This is the exact pattern observed in production: Apr 26 thread (18 items,
   works) alongside Apr 17 shadow mode messages (singletons, dropped).

3. Standalone user + assistant messages — both user messages and assistant
   artifacts have their own separate thread_refs.  All are singletons, all
   get no extraction.

Baseline comparison: messages sharing a single thread_ref extract facts normally.
"""
from __future__ import annotations

import json
from typing import Any

from app.config import AppConfig, LLMProviderConfig, SemanticPackageConfig
from app.main import create_app
from fastapi.testclient import TestClient
from providers.llm.base import LLMJsonResponse
from storage.vector_index import VectorIndexConfig


# ---------------------------------------------------------------------------
# Stub LLM provider
# ---------------------------------------------------------------------------

class FactExtractionStubProvider:
    """Returns realistic facts for catalog-sync design discussion.

    Each call returns facts with entirely different subjects and content so that
    paraphrase dedup across multiple extraction scopes cannot collapse them.
    """

    _FACT_SETS = [
        [
            {"subject": "catalog sync", "statement": "Catalog sync should run in shadow mode before enabling for all branches.", "category": "preference"},
            {"subject": "catalog sync rollout", "statement": "The proposed rollout has three stages: debug-only logging, shadow sync with quality measurement, and full sync.", "category": "event"},
            {"subject": "shadow sync evaluation", "statement": "Shadow mode evaluation works by pushing tagged updates that the catalog service ignores, allowing accuracy measurement without side effects.", "category": "activity"},
        ],
        [
            {"subject": "branch protection", "statement": "Branch protection rules must require at least two approvals before merge.", "category": "constraint"},
            {"subject": "deployment pipeline", "statement": "The deployment pipeline uses blue-green strategy with automatic rollback on health check failure.", "category": "architecture"},
            {"subject": "monitoring alerts", "statement": "Monitoring alerts fire when error rate exceeds five percent over a rolling five minute window.", "category": "threshold"},
        ],
        [
            {"subject": "data retention", "statement": "Data retention policy requires deletion of user data within thirty days of account closure.", "category": "constraint"},
            {"subject": "cache invalidation", "statement": "Cache invalidation uses event-driven approach where writes publish to invalidation topic.", "category": "architecture"},
            {"subject": "rate limiting", "statement": "Rate limiting is set to one hundred requests per minute per authenticated client.", "category": "threshold"},
        ],
    ]

    def __init__(self):
        self._call_count = 0

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str,
    ) -> LLMJsonResponse:
        if "atomic fact" in system_prompt.lower() or '"category"' in schema_description:
            self._call_count += 1
            fact_set = self._FACT_SETS[(self._call_count - 1) % len(self._FACT_SETS)]
            payload = {"facts": list(fact_set)}
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)
        payload = {"summary": "Design discussion about catalog sync shadow mode rollout."}
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _config(test_db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="demo_agent_memory",
        llm_providers={
            "test_provider": LLMProviderConfig(
                name="test_provider",
                kind="openai_compatible",
                base_url="http://fake-provider.local",
                api_key="test-key",
                timeout_seconds=30.0,
            ),
        },
        semantic_packages={
            "demo_agent_memory": SemanticPackageConfig(name="demo_agent_memory", implementation="demo_agent_memory"),
            "conversational_knowledge": SemanticPackageConfig(
                name="conversational_knowledge",
                implementation="conversational_knowledge",
                llm_provider="test_provider",
                model="fake-model",
            ),
        },
        vector_index=VectorIndexConfig(enabled=False),
    )


# ---------------------------------------------------------------------------
# Message content — neutral domain (catalog sync shadow mode)
# ---------------------------------------------------------------------------

CONTAINER_REF = "slack:dm:test-design-channel"

# Standalone top-level DM messages (user only — matches real Pelican pattern
# where assistant responses route to different threads)
STANDALONE_USER_MESSAGES = [
    "Should we run the catalog sync in shadow mode first before enabling it for all branches? I don't want to risk data corruption in the live catalog.",
    "I think we need a three-stage rollout: debug-only logging first, then shadow sync, then full sync once we measure quality.",
    "How do we evaluate sync quality during shadow mode? Our current quality checks rely on comparing live catalog state before and after.",
    "The simplest approach: push sync updates but tag them as shadow entries. The catalog service ignores tagged entries in queries but we can run accuracy comparisons offline.",
    "Before implementing any of this, let's design the tagging mechanism properly. I want to make sure we handle edge cases like partial syncs and tag cleanup.",
]

# Messages for a working threaded conversation (all in one thread, like
# a Slack thread where users reply in-thread)
THREADED_DEPLOYMENT_MESSAGES = [
    "Let's discuss how to deploy the catalog sync service. We need a strategy.",
    "I think blue-green deployment is safest here — we can roll back instantly if sync quality drops.",
    "What about canary? We could route 5% of branches first and compare catalog accuracy.",
    "Canary sounds better. Blue-green doesn't let us measure gradual impact. Let's go with canary at 5% initially.",
]

# Assistant responses — each with their own thread_ref (matches real pattern
# where Pelican routes artifacts to separate threads)
ASSISTANT_RESPONSES = [
    "Based on the catalog sync requirements, shadow mode would let us validate sync accuracy without affecting live data. I recommend starting with a debug-only phase.",
    "The three-stage rollout makes sense. For the shadow evaluation, we could use tagged entries that the catalog service filters out of production queries.",
    "I've drafted a tagging mechanism design. Shadow entries would use a prefix tag that the catalog query layer strips automatically.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_standalone_user_messages(prefix: str) -> list[dict[str, Any]]:
    """Each user message gets its own thread_ref — real Slack DM top-level pattern.

    In Slack, every top-level message has thread_ref = its own timestamp.
    Only explicit thread replies share a parent's thread_ref.  DM channels
    are predominantly top-level messages.
    """
    messages = []
    for i, content in enumerate(STANDALONE_USER_MESSAGES):
        thread_ts = f"1776430{600 + i * 100}.{100 + i:06d}"
        messages.append({
            "source_type": "conversation_agent_event",
            "source_id": f"{prefix}-standalone-user-{i}",
            "content_type": "text/plain",
            "content": content,
            "artifact_kind": "message",
            "role": "user",
            "container_ref": CONTAINER_REF,
            "thread_ref": f"slack:thread:test-design-channel:{thread_ts}",
            "visibility": "private",
        })
    return messages


def _make_threaded_messages(prefix: str) -> list[dict[str, Any]]:
    """All messages share the same thread_ref — a Slack threaded conversation.

    Users replying in-thread all share the parent message's thread_ref.
    This pattern produces 4 items in one thread, above the 2-item minimum.
    """
    shared_thread = "slack:thread:test-design-channel:1776430600.000000"
    messages = []
    for i, content in enumerate(THREADED_DEPLOYMENT_MESSAGES):
        messages.append({
            "source_type": "conversation_agent_event",
            "source_id": f"{prefix}-threaded-{i}",
            "content_type": "text/plain",
            "content": content,
            "artifact_kind": "message",
            "role": "user",
            "container_ref": CONTAINER_REF,
            "thread_ref": shared_thread,
            "visibility": "private",
        })
    return messages


def _make_mixed_container_messages(prefix: str) -> list[dict[str, Any]]:
    """A realistic DM channel: one multi-item thread + standalone top-level messages.

    Matches the real Pelican data pattern where the same container has:
    - A working thread (Apr 26: 18 items, extraction succeeds)
    - Standalone messages (Apr 17: 1 item each, extraction fails)
    """
    threaded = _make_threaded_messages(f"{prefix}-thread")
    standalone = _make_standalone_user_messages(f"{prefix}-orphan")
    return threaded + standalone


def _make_standalone_user_and_assistant_messages(prefix: str) -> list[dict[str, Any]]:
    """User and assistant messages each with their own thread_refs.

    Matches the real Pelican pattern where assistant artifacts route to
    different threads than user messages.  Both user and assistant messages
    end up as singletons.
    """
    messages = []
    # User messages — each with own thread_ref
    for i, content in enumerate(STANDALONE_USER_MESSAGES[:3]):
        thread_ts = f"1776430{600 + i * 100}.{100 + i:06d}"
        messages.append({
            "source_type": "conversation_agent_event",
            "source_id": f"{prefix}-user-{i}",
            "content_type": "text/plain",
            "content": content,
            "artifact_kind": "message",
            "role": "user",
            "container_ref": CONTAINER_REF,
            "thread_ref": f"slack:thread:test-design-channel:{thread_ts}",
            "visibility": "private",
        })
    # Assistant responses — each with their own DIFFERENT thread_ref
    for i, content in enumerate(ASSISTANT_RESPONSES):
        thread_ts = f"1776431{600 + i * 100}.{200 + i:06d}"
        messages.append({
            "source_type": "conversation_agent_artifact",
            "source_id": f"{prefix}-assistant-{i}",
            "content_type": "text/plain",
            "content": content,
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": CONTAINER_REF,
            "thread_ref": f"slack:thread:test-design-channel:{thread_ts}",
            "visibility": "private",
        })
    return messages


def _collect_facts(storage, container_ref: str) -> list:
    """Collect all atomic_fact memory objects in a container."""
    return storage.list_memory_objects(
        memory_types=["atomic_fact"],
        lifecycle="active",
        container_ref=container_ref,
    )


def _collect_source_items_without_fact_extraction(storage, container_ref: str) -> list:
    """Find source items that have no supported_by relation from any atomic_fact."""
    from storage.sqlite_schema import MemoryObjectRecord, RelationRecord, SourceItemRecord
    from sqlalchemy import select

    with storage._session_factory() as session:
        fact_ids = {
            r.id for r in session.scalars(
                select(MemoryObjectRecord).where(
                    MemoryObjectRecord.type == "atomic_fact",
                    MemoryObjectRecord.container_ref == container_ref,
                )
            ).all()
        }
        extracted_ids = {
            r.to_id for r in session.scalars(
                select(RelationRecord).where(
                    RelationRecord.relation_type == "supported_by",
                    RelationRecord.to_kind == "source_item",
                    RelationRecord.from_kind == "memory_object",
                    RelationRecord.from_id.in_(fact_ids) if fact_ids else False,
                )
            ).all()
        } if fact_ids else set()
        all_items = session.scalars(
            select(SourceItemRecord).where(
                SourceItemRecord.container_ref == container_ref,
            )
        ).all()
        return [r.id for r in all_items if r.id not in extracted_ids]


def _count_source_items(service, container_ref: str) -> int:
    from storage.sqlite_schema import SourceItemRecord
    from sqlalchemy import select, func

    with service._storage._session_factory() as session:
        return session.scalar(
            select(func.count()).select_from(SourceItemRecord).where(
                SourceItemRecord.container_ref == container_ref,
            )
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStandaloneMessageExtractionGap:
    """Demonstrates that standalone messages are ingested but never extracted."""

    def test_threaded_messages_produce_facts(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """Baseline: messages in a shared thread are extracted into atomic_facts."""
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactExtractionStubProvider(),
        )
        app = create_app(_config(test_db_url))
        client = TestClient(app)
        service = app.state.pallium_service

        for msg in _make_threaded_messages("baseline"):
            client.post("/items", json=[msg])
        service.drain_processing_queue(worker_id="drain")

        facts = _collect_facts(service._storage, CONTAINER_REF)
        assert len(facts) >= 1, (
            "Threaded messages should produce atomic_facts — "
            "this is the baseline that proves extraction works"
        )

    def test_standalone_user_messages_produce_no_facts(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """Container-level extraction picks up standalone user messages that
        each have their own thread_ref.  Even though each thread has only 1
        item (below the thread-level 2-item minimum), the container scope
        aggregates them and produces atomic_facts.
        """
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactExtractionStubProvider(),
        )
        app = create_app(_config(test_db_url))
        client = TestClient(app)
        service = app.state.pallium_service

        for msg in _make_standalone_user_messages("repro"):
            client.post("/items", json=[msg])
        service.drain_processing_queue(worker_id="drain")

        assert _count_source_items(service, CONTAINER_REF) == len(STANDALONE_USER_MESSAGES), (
            f"All {len(STANDALONE_USER_MESSAGES)} user messages should be ingested"
        )

        facts = _collect_facts(service._storage, CONTAINER_REF)
        assert len(facts) >= 1, (
            "Container-level extraction should produce atomic_facts "
            "from standalone user messages"
        )

        unextracted = _collect_source_items_without_fact_extraction(
            service._storage, CONTAINER_REF,
        )
        assert len(unextracted) == 0, (
            "All standalone messages should have fact extraction via container scope"
        )

    def test_mixed_container_thread_extracts_but_standalones_do_not(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """Real DM channel pattern: a working multi-item thread coexists
        with standalone orphan messages in the same container.

        Both the thread and the standalone messages produce facts: the thread
        via thread-level extraction, the standalone messages via container-level
        extraction.
        """
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactExtractionStubProvider(),
        )
        app = create_app(_config(test_db_url))
        client = TestClient(app)
        service = app.state.pallium_service

        for msg in _make_mixed_container_messages("mixed"):
            client.post("/items", json=[msg])
        service.drain_processing_queue(worker_id="drain")

        total_messages = len(THREADED_DEPLOYMENT_MESSAGES) + len(STANDALONE_USER_MESSAGES)
        assert _count_source_items(service, CONTAINER_REF) == total_messages, (
            f"All {total_messages} messages should be ingested"
        )

        facts = _collect_facts(service._storage, CONTAINER_REF)
        assert len(facts) >= 1, (
            "The multi-item thread should produce facts"
        )

        # The standalone messages have no fact extraction despite being in
        # the same container as a working thread
        unextracted = _collect_source_items_without_fact_extraction(
            service._storage, CONTAINER_REF,
        )
        assert len(unextracted) == 0, (
            "All messages should have fact extraction — thread-level for the "
            "multi-item thread, container-level for standalone messages"
        )

    def test_standalone_user_and_assistant_both_orphaned(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """Both user messages and assistant artifacts are singletons when
        they have separate thread_refs.

        Container-level extraction picks up both user and assistant top-level
        messages and produces atomic_facts from the aggregated content.
        """
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactExtractionStubProvider(),
        )
        app = create_app(_config(test_db_url))
        client = TestClient(app)
        service = app.state.pallium_service

        messages = _make_standalone_user_and_assistant_messages("both")
        for msg in messages:
            client.post("/items", json=[msg])
        service.drain_processing_queue(worker_id="drain")

        total_messages = 3 + len(ASSISTANT_RESPONSES)  # 3 user + 3 assistant
        assert _count_source_items(service, CONTAINER_REF) == total_messages, (
            f"All {total_messages} messages (user + assistant) should be ingested"
        )

        facts = _collect_facts(service._storage, CONTAINER_REF)
        assert len(facts) >= 1, (
            "Container-level extraction should produce atomic_facts "
            "from standalone user and assistant messages"
        )

    def test_standalone_messages_create_completed_scopes(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """Thread processing scopes are created and completed for each
        standalone message's thread, plus a container-level scope that
        aggregates them for extraction."""
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactExtractionStubProvider(),
        )
        app = create_app(_config(test_db_url))
        client = TestClient(app)
        service = app.state.pallium_service

        for msg in _make_standalone_user_messages("scope"):
            client.post("/items", json=[msg])
        service.drain_processing_queue(worker_id="drain")

        from storage.sqlite_schema import ThreadProcessingLeaseRecord
        from sqlalchemy import select

        with service._storage._session_factory() as session:
            scopes = session.scalars(
                select(ThreadProcessingLeaseRecord).where(
                    ThreadProcessingLeaseRecord.container_ref == CONTAINER_REF,
                )
            ).all()

        assert len(scopes) >= len(STANDALONE_USER_MESSAGES), (
            f"Expected at least {len(STANDALONE_USER_MESSAGES)} scopes "
            f"(one per standalone thread_ref), got {len(scopes)}"
        )

        for scope in scopes:
            assert scope.requested_at is None, (
                f"Scope {scope.scope_key} still has pending request"
            )
            assert scope.processing_completed_at is not None, (
                f"Scope {scope.scope_key} was never processed"
            )

        container_scopes = [s for s in scopes if '"thread_ref":null' in s.scope_key]
        assert len(container_scopes) >= 1, (
            "Container scope should be created for the container"
        )
