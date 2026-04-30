"""Reproduction test for thread summary accumulation bug.

Simulates the production topology with BOTH semantic packages
(agent_conversation_memory + conversational_knowledge) running in parallel,
which is how Pallium always runs in production.

The goal is to reproduce the reported issue: 21 active thread_summaries from
a 12-message thread, where supersession should leave only 1 active.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from app.config import AppConfig, LLMProviderConfig, SemanticPackageConfig
from app.dependencies import build_service
from app.main import create_app
from capabilities.consolidation import ConsolidationPolicy, DEFAULT_CONSOLIDATION_STRATEGIES
from fastapi.testclient import TestClient
from providers.llm.base import LLMJsonResponse
from storage.vector_index import VectorIndexConfig
from tests.test_thread_aggregation import ThreadAwareStubProvider


# ---------------------------------------------------------------------------
# Stub provider that handles BOTH agent_conversation_memory and
# conversational_knowledge LLM calls.
# ---------------------------------------------------------------------------

class DualPackageStubProvider(ThreadAwareStubProvider):
    """Extends ThreadAwareStubProvider with conversational_knowledge fact extraction."""

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        # Detect conversational_knowledge fact extraction calls
        if "atomic fact" in system_prompt.lower() or '"category"' in schema_description:
            payload = {"facts": [
                {"subject": "reservation ordering", "statement": "Item event time is used for reservation ordering.", "category": "event"},
                {"subject": "catalog sync", "statement": "Catalog sync delays can cause skipped holds.", "category": "event"},
            ]}
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)
        # Otherwise delegate to the agent_conversation_memory stub
        return super().generate_json(system_prompt=system_prompt, user_prompt=user_prompt, schema_description=schema_description)


def _dual_package_config(test_db_url: str) -> AppConfig:
    """Config with both agent_conversation_memory AND conversational_knowledge — like production."""
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="agent_conversation_memory",
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
            "agent_conversation_memory": SemanticPackageConfig(
                name="agent_conversation_memory",
                implementation="agent_conversation_memory",
                llm_provider="test_provider",
                model="fake-model",
                prompt_variant="strict_typed_memory_v6_work_state_examples",
                consolidation=ConsolidationPolicy(
                    enabled_strategies=DEFAULT_CONSOLIDATION_STRATEGIES,
                    default_strategy="thread_summary_anchored",
                    max_candidates_per_run=24,
                    max_group_size=4,
                    same_container_required=True,
                    time_window_hours=168,
                    lexical_overlap_threshold=2,
                ),
            ),
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
# Helpers
# ---------------------------------------------------------------------------

def _collect_memory(storage, container_ref: str, thread_ref: str, memory_type: str | None = None):
    """Collect memory objects for a thread, optionally filtered by type."""
    thread_items = storage.list_source_items_for_thread(container_ref, thread_ref)
    all_memory: dict[str, Any] = {}
    for item in thread_items:
        for memory in storage.list_memory_objects_for_source_item(item.id):
            if memory_type is None or memory.type == memory_type:
                all_memory[memory.id] = memory
    return list(all_memory.values())


def _report(label: str, summaries, memory_type: str = "thread_summary"):
    active = [s for s in summaries if s.lifecycle == "active"]
    superseded = [s for s in summaries if s.lifecycle == "superseded"]
    print(f"\n{'='*60}")
    print(f"{label} [{memory_type}]")
    print(f"Total: {len(summaries)}, Active: {len(active)}, Superseded: {len(superseded)}")
    for s in summaries:
        extra = ""
        if memory_type == "atomic_fact":
            extra = f" stmt={str(s.payload.get('statement', ''))[:50]}"
        elif memory_type == "thread_summary":
            extra = f" sum={str(s.payload.get('summary', ''))[:50]}"
        print(f"  {s.id[:12]} lifecycle={s.lifecycle}{extra}")
    print(f"{'='*60}")
    return active


def _make_messages(prefix: str, count: int, container_ref: str, thread_ref: str):
    messages = []
    for i in range(1, count + 1):
        role = "user" if i % 2 == 1 else "assistant"
        source_type = "chat_message" if role == "user" else "assistant_artifact"
        artifact_kind = "message" if role == "user" else "assistant_output"
        messages.append({
            "source_type": source_type,
            "source_id": f"{prefix}-{i}",
            "content_type": "text/plain",
            "content": f"Message {i} about reservation ordering and catalog sync delays affecting hold updates during concurrent processing across all background worker instances.",
            "artifact_kind": artifact_kind,
            "role": role,
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "public",
        })
    return messages


# ---------------------------------------------------------------------------
# Scenario 1: Dual-package, single service, synchronous drain (baseline)
# ---------------------------------------------------------------------------

def test_dual_package_baseline_drain(monkeypatch, test_db_url: str) -> None:
    """Both packages, single service, synchronous drain."""
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: DualPackageStubProvider())
    config = _dual_package_config(test_db_url)
    app = create_app(config)
    client = TestClient(app)
    service = app.state.pallium_service

    thread_ref = "chat:test:thread-dual-baseline"
    container_ref = "chat:test"

    for msg in _make_messages("dual-base", 7, container_ref, thread_ref):
        client.post("/items", json=[msg])
        service.drain_processing_queue(worker_id="drain-worker")

    summaries = _collect_memory(service._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = _report("Dual-package baseline drain", summaries, "thread_summary")

    facts = _collect_memory(service._storage, container_ref, thread_ref, "atomic_fact")
    active_facts = _report("Dual-package baseline drain", facts, "atomic_fact")

    assert len(active_summaries) == 1, f"Expected 1 active thread_summary, got {len(active_summaries)}"


# ---------------------------------------------------------------------------
# Scenario 2: Dual-package, two instances, sequential
# ---------------------------------------------------------------------------

def test_dual_package_two_instances_sequential(monkeypatch, test_db_url: str) -> None:
    """Both packages, two service instances, items via A, rebuilds via B."""
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: DualPackageStubProvider())
    config = _dual_package_config(test_db_url)

    app_a = create_app(config)
    client_a = TestClient(app_a)
    service_a = app_a.state.pallium_service
    service_b = build_service(config, enable_vector=False)

    thread_ref = "chat:test:thread-dual-seq"
    container_ref = "chat:test"

    for msg in _make_messages("dual-seq", 7, container_ref, thread_ref):
        client_a.post("/items", json=[msg])
        # Process all package tasks via A
        while service_a.process_next_source_item(
            worker_id="worker-a", lease_seconds=60, max_attempts=3
        ) is not None:
            pass
        # Thread rebuilds via B (separate storage engine)
        while service_b.process_next_thread_rebuild(worker_id="worker-b", lease_seconds=60) is not None:
            pass

    summaries = _collect_memory(service_a._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = _report("Dual-package two-instance sequential", summaries, "thread_summary")

    facts = _collect_memory(service_a._storage, container_ref, thread_ref, "atomic_fact")
    active_facts = _report("Dual-package two-instance sequential", facts, "atomic_fact")

    assert len(active_summaries) == 1, f"Expected 1 active thread_summary, got {len(active_summaries)}"


# ---------------------------------------------------------------------------
# Scenario 3: Dual-package, concurrent worker threads
# ---------------------------------------------------------------------------

def test_dual_package_concurrent_workers(monkeypatch, test_db_url: str) -> None:
    """Both packages, two concurrent worker threads with separate service instances."""
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: DualPackageStubProvider())
    config = _dual_package_config(test_db_url)

    app = create_app(config)
    client = TestClient(app)
    service_w1 = build_service(config, enable_vector=False)
    service_w2 = build_service(config, enable_vector=False)

    thread_ref = "chat:test:thread-dual-concurrent"
    container_ref = "chat:test"

    stop_event = threading.Event()
    errors: list[Exception] = []

    def worker_loop(service, worker_id: str):
        try:
            while not stop_event.is_set():
                try:
                    result = service.process_next_source_item(
                        worker_id=worker_id, lease_seconds=60, max_attempts=3
                    )
                    if result is not None:
                        continue
                    lease = service.process_next_thread_rebuild(
                        worker_id=worker_id, lease_seconds=60
                    )
                    if lease is not None:
                        continue
                except Exception as exc:
                    if "database is locked" in str(exc):
                        time.sleep(0.1)
                        continue
                    raise
                time.sleep(0.05)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker_loop, args=(service_w1, "worker-1"), daemon=True)
    t2 = threading.Thread(target=worker_loop, args=(service_w2, "worker-2"), daemon=True)
    t1.start()
    t2.start()

    for msg in _make_messages("dual-conc", 12, container_ref, thread_ref):
        for _attempt in range(5):
            try:
                client.post("/items", json=[msg])
                break
            except Exception as exc:
                if "database is locked" in str(exc) and _attempt < 4:
                    time.sleep(0.2)
                    continue
                raise
        time.sleep(0.1)

    time.sleep(3.0)
    stop_event.set()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors, f"Worker errors: {errors}"

    summaries = _collect_memory(app.state.pallium_service._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = _report("Dual-package CONCURRENT", summaries, "thread_summary")

    facts = _collect_memory(app.state.pallium_service._storage, container_ref, thread_ref, "atomic_fact")
    active_facts = _report("Dual-package CONCURRENT", facts, "atomic_fact")

    assert len(active_summaries) == 1, f"Expected 1 active thread_summary, got {len(active_summaries)}"


# ---------------------------------------------------------------------------
# Scenario 4: Dual-package, concurrent, rapid-fire
# ---------------------------------------------------------------------------

def test_dual_package_concurrent_rapid_fire(monkeypatch, test_db_url: str) -> None:
    """Both packages, concurrent workers, all 12 messages rapid-fire."""
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: DualPackageStubProvider())
    config = _dual_package_config(test_db_url)

    app = create_app(config)
    client = TestClient(app)
    service_w1 = build_service(config, enable_vector=False)
    service_w2 = build_service(config, enable_vector=False)

    thread_ref = "chat:test:thread-dual-rapid"
    container_ref = "chat:test"

    stop_event = threading.Event()
    errors: list[Exception] = []

    def worker_loop(service, worker_id: str):
        try:
            while not stop_event.is_set():
                try:
                    result = service.process_next_source_item(
                        worker_id=worker_id, lease_seconds=60, max_attempts=3
                    )
                    if result is not None:
                        continue
                    lease = service.process_next_thread_rebuild(
                        worker_id=worker_id, lease_seconds=60
                    )
                    if lease is not None:
                        continue
                except Exception as exc:
                    if "database is locked" in str(exc):
                        time.sleep(0.1)
                        continue
                    raise
                time.sleep(0.02)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker_loop, args=(service_w1, "worker-1"), daemon=True)
    t2 = threading.Thread(target=worker_loop, args=(service_w2, "worker-2"), daemon=True)
    t1.start()
    t2.start()

    # All messages at once — retry on database-locked under concurrent workers
    for msg in _make_messages("dual-rapid", 12, container_ref, thread_ref):
        for _attempt in range(10):
            try:
                resp = client.post("/items", json=[msg])
                if resp.status_code == 200:
                    break
            except Exception as exc:
                if "database is locked" not in str(exc):
                    raise
            time.sleep(0.05)
        else:
            raise AssertionError("Ingest failed after retries: database is locked")

    for _poll in range(60):
        summaries = _collect_memory(app.state.pallium_service._storage, container_ref, thread_ref, "thread_summary")
        if any(mo.lifecycle == "active" for mo in summaries):
            break
        time.sleep(0.5)

    stop_event.set()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors, f"Worker errors: {errors}"

    summaries = _collect_memory(app.state.pallium_service._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = _report("Dual-package RAPID-FIRE", summaries, "thread_summary")

    facts = _collect_memory(app.state.pallium_service._storage, container_ref, thread_ref, "atomic_fact")
    active_facts = _report("Dual-package RAPID-FIRE", facts, "atomic_fact")

    assert len(active_summaries) == 1, f"Expected 1 active thread_summary, got {len(active_summaries)}"
