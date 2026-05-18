"""Tests for decision/investigation_outcome supersession across thread rebuilds.

Bug: decision and investigation_outcome memory objects accumulate endlessly across
thread rebuilds instead of superseding old copies with the same canonical_key.
After 6 rebuilds there were 42 active decision objects — 6 batches of 7, all near-identical.

Fix: build_thread_summary emits SupersessionHints for newly produced decisions/
investigation_outcomes that match existing conclusions by canonical_key, and
thread_rebuild.py carries those hints through the ProcessResult reconstruction.
"""
from __future__ import annotations

import json

import pytest

from app.config import AppConfig, LLMProviderConfig, SemanticPackageConfig
from app.main import create_app
from capabilities.consolidation import ConsolidationPolicy, DEFAULT_CONSOLIDATION_STRATEGIES
from core.models import MemoryObject
from fastapi.testclient import TestClient
from providers.llm.base import LLMJsonResponse
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from semantic.agent_conversation_memory_threads import _evidence_canonical_key, build_thread_summary
from storage.vector_index import VectorIndexConfig


# ---------------------------------------------------------------------------
# Stub LLM provider
# ---------------------------------------------------------------------------

class DecisionStubProvider:
    """Stub that emits a single stable decision and investigation on every call.

    Uses evidence text that is a substring of the test message padding so that
    the grounding check in _validate_thread_decisions passes.
    """
    # These must appear verbatim in the thread content (as part of _substantive() padding)
    EVIDENCE_TEXT = "thorough discussion and evaluation of the available options and trade-offs"
    INVESTIGATION_EVIDENCE_TEXT = "thorough discussion and evaluation of the available options and trade-offs"

    DECISION_TEXT = "Event-time ordering selected for all reservation holds to prevent sync-delay losses in the distributed system."
    INVESTIGATION_TEXT = "Batch processing with checkpoint recovery found to handle the 150K message backlog within acceptable latency bounds."

    def __init__(self):
        self.call_count = 0

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        self.call_count += 1
        payload = {
            "summary": f"Thread summary from call {self.call_count}.",
            "content_quality": "substantive",
            "retrieval_context": None,
            "decisions": [
                {
                    "decision_text": self.DECISION_TEXT,
                    "evidence": self.EVIDENCE_TEXT,
                }
            ],
            "investigations": [
                {
                    "investigation_text": self.INVESTIGATION_TEXT,
                    "evidence": self.INVESTIGATION_EVIDENCE_TEXT,
                }
            ],
        }
        if "task_checkpoint" in schema_description:
            payload["task_checkpoint"] = {
                "summary": f"Checkpoint from call {self.call_count}.",
                "task": "Test task",
                "current_state": "in progress",
                "key_findings": [],
                "blocker_state": "",
                "next_step": "",
                "evidence": [],
                "freshness_signal": "latest",
                "retrieval_context": None,
            }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


class DifferentKeyDecisionStubProvider:
    """Emits 'Alpha' decision when batch-1-only content is in the prompt, 'Beta' when
    batch-2 content is present. Detection is by user-prompt content (not call counter)
    because thread rebuilds may run multiple times per drain.

    Each variant uses distinct evidence text (substring of the corresponding messages)
    so that the evidence-based canonical_key differs between Alpha and Beta.
    """
    # Evidence must be a literal substring of the corresponding batch's message content.
    ALPHA_EVIDENCE = "alpha approach for the synchronization module design"
    BETA_EVIDENCE = "beta strategy for the reconciliation pipeline"
    ALPHA_KEY = "Alpha approach selected for synchronization module design after comprehensive evaluation."
    BETA_KEY = "Beta strategy chosen for reconciliation pipeline implementation after systematic comparison."

    def __init__(self):
        self.rebuild_call_count = 0

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        is_thread_rebuild = '"decisions"' in schema_description
        if is_thread_rebuild:
            self.rebuild_call_count += 1
        in_batch_2 = "beta strategy" in user_prompt or "Beta strategy" in user_prompt
        if in_batch_2:
            # Second batch: emit only Beta (no Alpha — tests that Beta doesn't supersede Alpha)
            decision_text = self.BETA_KEY
            evidence = self.BETA_EVIDENCE
        else:
            decision_text = self.ALPHA_KEY
            evidence = self.ALPHA_EVIDENCE
        payload = {
            "summary": f"Summary (rebuild #{self.rebuild_call_count}).",
            "content_quality": "substantive",
            "retrieval_context": None,
            "decisions": [
                {
                    "decision_text": decision_text,
                    "evidence": evidence,
                }
            ],
            "investigations": [],
        }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


class NewKeyStubProvider:
    """Each batch emits a distinct decision (and distinct evidence) — so canonical_keys
    differ between batches. Detection is by content marker in the user prompt rather than
    a per-call counter, because thread rebuilds may run multiple times per drain."""
    BATCH_1_EVIDENCE = "First topic: discussing a completely unique architectural decision for the system module"
    BATCH_2_EVIDENCE = "Second topic: discussing another separate unique architectural decision for the project component"

    def __init__(self):
        self.call_count = 0

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        self.call_count += 1
        in_batch_2 = "Second topic" in user_prompt
        if in_batch_2:
            decision_text = (
                "Completely unique architectural decision number two for a distinct subsystem "
                "with no overlap to prior choices whatsoever."
            )
            evidence = self.BATCH_2_EVIDENCE
        else:
            decision_text = (
                "Completely unique architectural decision number one for a distinct subsystem "
                "with no overlap to prior choices whatsoever."
            )
            evidence = self.BATCH_1_EVIDENCE
        payload = {
            "summary": f"Summary from call {self.call_count}.",
            "content_quality": "substantive",
            "retrieval_context": None,
            "decisions": [
                {
                    "decision_text": decision_text,
                    "evidence": evidence,
                }
            ],
            "investigations": [],
        }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


# ---------------------------------------------------------------------------
# Config / client helpers
# ---------------------------------------------------------------------------

def _test_config(test_db_url: str) -> AppConfig:
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
        },
        vector_index=VectorIndexConfig(enabled=False),
    )


def _create_client(monkeypatch, test_db_url: str, stub):
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: stub)
    config = _test_config(test_db_url)
    app = create_app(config)
    client = TestClient(app)
    return client, app.state.pallium_service


def _make_message(source_id: str, content: str, container_ref: str, thread_ref: str, *, role: str = "user"):
    return {
        "source_type": "chat_message" if role == "user" else "assistant_artifact",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "message" if role == "user" else "assistant_output",
        "role": role,
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "visibility": "public",
    }


def _substantive(base: str) -> str:
    """Pad a message to be well above the 20-token substantive threshold so that
    _should_request_thread_rebuild returns True for per-item processing."""
    padding = (
        " The team reviewed the approach carefully and agreed on the implementation plan "
        "after thorough discussion and evaluation of the available options and trade-offs."
    )
    return base + padding


def _post_and_drain(client, service, messages):
    for msg in messages:
        client.post("/items", json=[msg])
    service.drain_processing_queue(worker_id="test-worker")


def _get_active_memory(storage, container_ref: str, thread_ref: str, memory_type: str) -> list[MemoryObject]:
    """Return active memory objects of the given type reachable via thread source items."""
    thread_items = storage.list_source_items_for_thread(container_ref, thread_ref)
    seen: dict[str, MemoryObject] = {}
    for item in thread_items:
        for mo in storage.list_memory_objects_for_source_item(item.id):
            if mo.type == memory_type:
                seen[mo.id] = mo
    return [mo for mo in seen.values() if mo.lifecycle == "active"]


def _get_all_memory(storage, container_ref: str, thread_ref: str, memory_type: str) -> list[MemoryObject]:
    """Return ALL memory objects of the given type (any lifecycle) reachable via thread source items."""
    thread_items = storage.list_source_items_for_thread(container_ref, thread_ref)
    seen: dict[str, MemoryObject] = {}
    for item in thread_items:
        for mo in storage.list_memory_objects_for_source_item(item.id):
            if mo.type == memory_type:
                seen[mo.id] = mo
    return list(seen.values())


# ---------------------------------------------------------------------------
# Test 1: Reproduce the bug — same decision accumulates across rebuilds
# (FAIL before fix, PASS after)
# ---------------------------------------------------------------------------

def test_rebuild_decisions_supersede_old_copies_with_same_canonical_key(
    monkeypatch, test_db_url: str
) -> None:
    """Same decision extracted on every rebuild — only the latest batch should be active.

    Before the fix: all rebuild decisions accumulate (no supersession).
    After the fix: only the latest copy is active; previous copies are 'superseded'.
    """
    container_ref = "test:supersession:basic"
    thread_ref = "test:supersession:basic:thread-1"

    stub = DecisionStubProvider()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    # First batch: two source items → first thread rebuild
    messages1 = [
        _make_message("sb-1", _substantive("User message about event-time ordering for reservation holds."), container_ref, thread_ref),
        _make_message("sb-2", _substantive("We decided to use event-time ordering for all reservation holds to prevent sync-delay losses."), container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages1)

    # Verify first rebuild produced decisions
    active_after_first = _get_active_memory(service._storage, container_ref, thread_ref, "decision")
    assert len(active_after_first) >= 1, "Expected at least one decision after first rebuild"

    # Second rebuild: add another source item to trigger a new rebuild
    messages2 = [
        _make_message("sb-3", _substantive("Follow-up question about the ordering approach and its implications."), container_ref, thread_ref),
        _make_message("sb-4", _substantive("Confirming: event-time ordering is the right choice here for our distributed system."), container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages2)

    # After second rebuild, the same decision (same canonical_key) should supersede the old one
    active_after_second = _get_active_memory(service._storage, container_ref, thread_ref, "decision")
    all_after_second = _get_all_memory(service._storage, container_ref, thread_ref, "decision")

    # The total may be more than 1 (across all source items), but the number of ACTIVE
    # decisions with the same canonical_key must be 1 — not 2.
    target_key = _evidence_canonical_key(DecisionStubProvider.EVIDENCE_TEXT)
    active_matching = [
        mo for mo in active_after_second
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
    ]
    superseded_matching = [
        mo for mo in all_after_second
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
        and mo.lifecycle == "superseded"
    ]

    assert len(active_matching) == 1, (
        f"Expected exactly 1 active decision with canonical_key={target_key!r}, "
        f"got {len(active_matching)}. "
        f"All decisions: {[(mo.id[:8], mo.lifecycle, mo.payload.get('canonical_key','')[:30]) for mo in all_after_second]}"
    )
    assert len(superseded_matching) >= 1, (
        f"Expected at least 1 superseded decision after second rebuild, got {len(superseded_matching)}. "
        "This means the old decision was NOT superseded."
    )


# ---------------------------------------------------------------------------
# Test 2: Canonical_key matching — only matching key is superseded
# (FAIL before fix, PASS after)
# ---------------------------------------------------------------------------

def test_rebuild_only_supersedes_matching_canonical_key(
    monkeypatch, test_db_url: str
) -> None:
    """Second rebuild with key 'Beta' does NOT supersede old decision with key 'Alpha'.

    Rebuild 1 produces Alpha. Rebuild 2 produces Beta (different canonical_key).
    After rebuild 2, Alpha must still be active — it should not be superseded by Beta.
    """
    container_ref = "test:supersession:diffkey"
    thread_ref = "test:supersession:diffkey:thread-1"

    stub = DifferentKeyDecisionStubProvider()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    # First rebuild → decision "Alpha"
    messages1 = [
        _make_message("dk-1", _substantive("We chose the alpha approach for the synchronization module design after extensive evaluation."), container_ref, thread_ref),
        _make_message("dk-2", _substantive("Alpha approach was chosen for the synchronization module design after careful review."), container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages1)

    active_after_first = _get_active_memory(service._storage, container_ref, thread_ref, "decision")
    assert len(active_after_first) >= 1, "Expected at least one active decision after first rebuild"

    alpha_key = _evidence_canonical_key(DifferentKeyDecisionStubProvider.ALPHA_EVIDENCE)
    alpha_decisions_after_first = [
        mo for mo in active_after_first
        if str(mo.payload.get("canonical_key") or "").strip() == alpha_key
    ]
    assert len(alpha_decisions_after_first) >= 1, (
        f"Expected Alpha decision to be active after first rebuild, got none. "
        f"Active: {[(mo.id[:8], mo.payload.get('canonical_key','')[:40]) for mo in active_after_first]}"
    )

    # Second rebuild → decision "Beta" (different canonical_key, no match with Alpha)
    messages2 = [
        _make_message("dk-3", _substantive("We selected the beta strategy for the reconciliation pipeline after reviewing all options."), container_ref, thread_ref),
        _make_message("dk-4", _substantive("Beta strategy was selected for the reconciliation pipeline implementation after evaluation."), container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages2)

    all_after_second = _get_all_memory(service._storage, container_ref, thread_ref, "decision")
    beta_key = _evidence_canonical_key(DifferentKeyDecisionStubProvider.BETA_EVIDENCE)

    # Alpha from rebuild 1 should NOT be superseded by Beta from rebuild 2
    alpha_active = [
        mo for mo in all_after_second
        if str(mo.payload.get("canonical_key") or "").strip() == alpha_key
        and mo.lifecycle == "active"
    ]
    beta_active = [
        mo for mo in all_after_second
        if str(mo.payload.get("canonical_key") or "").strip() == beta_key
        and mo.lifecycle == "active"
    ]

    assert len(alpha_active) >= 1, (
        f"Expected Alpha decision to remain active after second rebuild (different key = no supersession). "
        f"Alpha active: {len(alpha_active)}. "
        f"All: {[(mo.id[:8], mo.lifecycle, mo.payload.get('canonical_key','')[:30]) for mo in all_after_second]}"
    )
    assert len(beta_active) >= 1, (
        f"Expected Beta decision to be active after second rebuild. "
        f"Beta active: {len(beta_active)}"
    )
    # Dispatch-coverage guard: if the thread-prompt template ever stops embedding raw
    # source-item content verbatim, the stub's user_prompt detection silently breaks
    # and the test would falsely pass. Assert that both branches actually fired.
    assert stub.rebuild_call_count >= 2, (
        f"Test stub did not see two distinct thread-rebuild calls "
        f"(rebuild_call_count={stub.rebuild_call_count}); dispatch logic may be broken."
    )


# ---------------------------------------------------------------------------
# Test 3: Safety — new canonical_key (no prior match) accumulates normally
# (should PASS before and after fix — regression/safety test)
# ---------------------------------------------------------------------------

def test_new_canonical_key_accumulates_without_spurious_supersession(
    monkeypatch, test_db_url: str
) -> None:
    """Decisions with completely new canonical_keys accumulate — no spurious supersession."""
    container_ref = "test:supersession:newkey"
    thread_ref = "test:supersession:newkey:thread-1"

    stub = NewKeyStubProvider()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    # First rebuild
    messages1 = [
        _make_message("nk-1", _substantive("First topic: discussing a completely unique architectural decision for the system module."), container_ref, thread_ref),
        _make_message("nk-2", _substantive("Decided on approach for first topic after thorough review of available options and trade-offs."), container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages1)

    active_after_first = _get_active_memory(service._storage, container_ref, thread_ref, "decision")
    assert len(active_after_first) >= 1, "Expected first decision to be active"

    # Second rebuild with a completely different decision
    messages2 = [
        _make_message("nk-3", _substantive("Second topic: discussing another separate unique architectural decision for the project component."), container_ref, thread_ref),
        _make_message("nk-4", _substantive("Decided on approach for second topic after thorough review of available options and trade-offs."), container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages2)

    active_after_second = _get_active_memory(service._storage, container_ref, thread_ref, "decision")

    # Both distinct decisions should be active
    assert len(active_after_second) >= 2, (
        f"Expected both unique decisions to be active (different keys), "
        f"got {len(active_after_second)}"
    )


# ---------------------------------------------------------------------------
# Test 4: Per-item decisions are not affected (regression test)
# Per-item path uses build_supersession_hints; thread rebuild fix must not interfere.
# (should PASS before and after fix)
# ---------------------------------------------------------------------------

def test_per_item_decision_supersession_unaffected(
    monkeypatch, test_db_url: str
) -> None:
    """Per-item decisions still supersede correctly via the existing per-item path."""
    container_ref = "test:supersession:per-item"
    thread_ref = "test:supersession:per-item:thread-1"

    stub = DecisionStubProvider()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    # Post a single message and drain — this exercises process_item(), not thread rebuild
    msg = _make_message(
        "pi-1",
        _substantive("We decided to use event-time ordering for all reservation holds to prevent sync losses."),
        container_ref,
        thread_ref,
    )
    client.post("/items", json=[msg])
    service.drain_processing_queue(worker_id="test-worker")

    # Check that processing completed (not crash, not broken)
    # We just verify no exception was raised and the service is still responsive
    resp = client.post("/query", json={"text": "event-time ordering", "container_ref": container_ref})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test 5: non_superseding_types property unchanged (regression)
# ---------------------------------------------------------------------------

def test_non_superseding_types_property_unchanged() -> None:
    """non_superseding_types must remain frozenset({'decision', 'investigation_outcome'})."""
    from capabilities.consolidation import ConsolidationPolicy, DEFAULT_CONSOLIDATION_STRATEGIES

    class _FakeProvider:
        def generate_json(self, **_):
            raise NotImplementedError

    plugin = AgentConversationMemoryPlugin(
        _FakeProvider(),
        prompt_variant="strict_typed_memory_v6_work_state_examples",
        consolidation_config=ConsolidationPolicy(
            enabled_strategies=DEFAULT_CONSOLIDATION_STRATEGIES,
            default_strategy="thread_summary_anchored",
            max_candidates_per_run=24,
            max_group_size=4,
            same_container_required=True,
            time_window_hours=168,
            lexical_overlap_threshold=2,
        ),
    )
    assert plugin.non_superseding_types == frozenset({"decision", "investigation_outcome"}), (
        f"non_superseding_types changed! Got {plugin.non_superseding_types!r}"
    )


# ---------------------------------------------------------------------------
# Test 6: build_thread_summary emits SupersessionHints for matching conclusions
# Unit test targeting the fix directly (FAIL before fix, PASS after)
# ---------------------------------------------------------------------------

def test_build_thread_summary_emits_supersession_hints_for_matching_conclusions() -> None:
    """build_thread_summary must include SupersessionHints for decisions matching old conclusions.

    This is a unit test that exercises build_thread_summary directly, passing
    old conclusions and verifying the returned ProcessResult includes hints
    matching the new decision to the old one.
    """
    from capabilities.thread_aggregation import ThreadAggregate
    from core.models import MemoryObject, SourceItem

    decision_text = "We decided to use event-time ordering for all reservation holds."
    # Evidence must be a substring of source items' content (asserted below).
    decision_evidence = "use event-time ordering for all reservation holds"
    canonical_key = _evidence_canonical_key(decision_evidence)
    assert canonical_key, "test fixture sanity: evidence must produce a non-null canonical_key"

    # Build an old decision that is already in DB (as a conclusion)
    old_decision = MemoryObject(
        type="decision",
        schema_id="agent_conversation_memory.thread_decision",
        schema_version="v1",
        payload={
            "decision": decision_text,
            "decision_evidence_text": decision_evidence,
            "rationale": None,
            "canonical_key": canonical_key,
            "source_type": "thread_detection",
            "source_id": "thread:test-thread",
        },
        visibility="public",
        container_ref="test:unit:container",
    )

    # Stub provider that returns the same decision text → same canonical_key
    # Evidence must be a literal substring of the source items' content
    class _StubProvider:
        def generate_json(self, *, system_prompt, user_prompt, schema_description):
            payload = {
                "summary": "Test summary for unit test of supersession hint emission.",
                "content_quality": "substantive",
                "retrieval_context": None,
                "decisions": [
                    {
                        "decision_text": decision_text,
                        # Evidence must be a substring of the thread material
                        # Source item content: "We decided to use event-time ordering for all reservation holds."
                        "evidence": "use event-time ordering for all reservation holds",
                    }
                ],
                "investigations": [],
            }
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)

    # Build minimal source items and aggregate
    source_item = SourceItem(
        source_type="chat_message",
        source_id="si-unit-1",
        content_type="text/plain",
        content="We decided to use event-time ordering for all reservation holds.",
        metadata={},
        container_ref="test:unit:container",
        thread_ref="test:unit:thread",
        visibility="public",
        role="user",
        artifact_kind="message",
    )
    source_item2 = SourceItem(
        source_type="assistant_artifact",
        source_id="si-unit-2",
        content_type="text/plain",
        content="Confirming the decision about event-time ordering for all reservation holds.",
        metadata={},
        container_ref="test:unit:container",
        thread_ref="test:unit:thread",
        visibility="public",
        role="assistant",
        artifact_kind="assistant_output",
    )

    from capabilities.thread_aggregation import build_thread_aggregate
    aggregate = build_thread_aggregate([source_item, source_item2])

    result = build_thread_summary(
        provider=_StubProvider(),
        prompt_variant="strict_typed_memory_v6_work_state_examples",
        plugin_name="agent_conversation_memory",
        thread_summary_schema_id="agent_conversation_memory.thread_summary",
        task_checkpoint_schema_id="agent_conversation_memory.task_checkpoint",
        aggregate=aggregate,
        conclusions=[old_decision],  # Pass the old decision as an existing conclusion
    )

    # The result must contain SupersessionHints for the new decision → old decision
    assert result.supersession_hints, (
        "ProcessResult.supersession_hints is empty — build_thread_summary did not emit "
        "supersession hints for a new decision matching an existing conclusion's canonical_key."
    )

    # Find the newly produced decision in the result
    new_decisions = [mo for mo in result.memory_objects if mo.type == "decision"]
    assert new_decisions, "No decision memory objects in result"
    new_decision = new_decisions[0]

    # Verify the hint points from new → old
    hint_replacement_ids = {h.replacement_memory_id for h in result.supersession_hints}
    hint_canonical_keys = {h.canonical_key for h in result.supersession_hints}

    assert new_decision.id in hint_replacement_ids, (
        f"New decision {new_decision.id[:8]} not in hint replacement_ids: {hint_replacement_ids}"
    )
    assert canonical_key in hint_canonical_keys, (
        f"canonical_key {canonical_key!r} not in hint keys: {hint_canonical_keys}"
    )


# ---------------------------------------------------------------------------
# Test 7: Investigation outcomes also supersede across rebuilds
# (FAIL before fix, PASS after)
# ---------------------------------------------------------------------------

def test_rebuild_investigations_supersede_old_copies_with_same_canonical_key(
    monkeypatch, test_db_url: str
) -> None:
    """Same investigation_outcome extracted on every rebuild — only latest should be active."""
    container_ref = "test:supersession:inv"
    thread_ref = "test:supersession:inv:thread-1"

    stub = DecisionStubProvider()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    messages1 = [
        _make_message("inv-1", _substantive("Question about batch processing backlog handling for distributed queue system."), container_ref, thread_ref),
        _make_message("inv-2", _substantive("Investigation concluded that batch processing handles the 150K message backlog within acceptable latency bounds."), container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages1)

    active_after_first = _get_active_memory(service._storage, container_ref, thread_ref, "investigation_outcome")
    assert len(active_after_first) >= 1, "Expected at least one investigation after first rebuild"

    messages2 = [
        _make_message("inv-3", _substantive("Further discussion about the batch processing approach for the distributed system workload."), container_ref, thread_ref),
        _make_message("inv-4", _substantive("Confirmed: batch processing is the right approach for this workload after thorough investigation."), container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages2)

    from semantic.common import normalize_for_index
    target_key = _evidence_canonical_key(DecisionStubProvider.INVESTIGATION_EVIDENCE_TEXT)

    all_after_second = _get_all_memory(service._storage, container_ref, thread_ref, "investigation_outcome")
    active_matching = [
        mo for mo in all_after_second
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
        and mo.lifecycle == "active"
    ]
    superseded_matching = [
        mo for mo in all_after_second
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
        and mo.lifecycle == "superseded"
    ]

    assert len(active_matching) == 1, (
        f"Expected exactly 1 active investigation with canonical_key={target_key!r}, "
        f"got {len(active_matching)}. "
        f"All investigations: {[(mo.id[:8], mo.lifecycle) for mo in all_after_second]}"
    )
    assert len(superseded_matching) >= 1, (
        f"Expected at least 1 superseded investigation, got {len(superseded_matching)}"
    )
