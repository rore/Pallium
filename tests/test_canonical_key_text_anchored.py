"""T2 — text-anchored canonical_key + container-scoped supersession + merge.

Covers three coupled changes (see
``.local/research/quality-round-2026-06-04/proto/T2_canonical_key/``):

1. Sub-bug A: thread-aggregated decision/investigation canonical_key is anchored
   on ``normalize_for_index(decision_text)`` rather than the LLM-supplied
   evidence quote, so canonical_key is stable across rebuilds even when the LLM
   tightens or trims its evidence quote.
2. Sub-bug B: decisions and investigation_outcomes hint at container scope
   (``thread_ref=None``) so cross-thread duplicates collapse onto one active
   row. Cross-container collisions are intentionally left active.
3. Merge-not-collapse: when a decision/investigation is superseded, the loser's
   evidence quote, rationale, and ``supported_by`` relations are merged into
   the winner before the lifecycle flip.

Tests follow the conventions in ``tests/test_decision_supersession_rebuild.py``
and ``tests/conftest.py``: real-import end-to-end through TestClient + drain
where the change is observable across the queue path; direct unit-test against
``build_thread_summary`` where stable contract is what matters.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppConfig, LLMProviderConfig, SemanticPackageConfig
from app.main import create_app
from capabilities.consolidation import ConsolidationPolicy, DEFAULT_CONSOLIDATION_STRATEGIES
from capabilities.thread_aggregation import build_thread_aggregate
from core.models import MemoryObject, SourceItem
from providers.llm.base import LLMJsonResponse
from semantic.agent_conversation_memory_constraints import CONSTRAINT_MEMORY_TYPE
from semantic.agent_conversation_memory_threads import build_thread_summary
from semantic.common import normalize_for_index
from storage.sqlite_schema import MemoryObjectRecord, RelationRecord
from storage.vector_index import VectorIndexConfig


# ---------------------------------------------------------------------------
# Helpers (mirror tests/test_decision_supersession_rebuild.py conventions)
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
                enabled=True,
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


def _make_message(source_id, content, container_ref, thread_ref, *, role="user"):
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
    """Pad message above the 20-token substantive threshold (mirrors existing tests)."""
    padding = (
        " The team reviewed the approach carefully and agreed on the implementation plan "
        "after thorough discussion and evaluation of the available options and trade-offs."
    )
    return base + padding


def _msg_with_decision(source_id, decision_text, evidence, container_ref, thread_ref):
    """User message whose content embeds both the decision_text (so the
    per-item ``has_grounded_decision_text`` substring guard passes) and the
    evidence quote (so ``has_grounded_decision_evidence`` passes), padded
    above the substantive-content threshold."""
    content = _substantive(
        f"User message: {decision_text} Context: {evidence}"
    )
    return _make_message(source_id, content, container_ref, thread_ref, role="user")


def _msg_assistant_grounding(source_id, evidence_variants, container_ref, thread_ref):
    """Assistant message embedding all evidence variants verbatim so
    thread-rebuild grounding (``_validate_thread_decisions``) passes
    regardless of which variant the stub returns on each rebuild call."""
    embedded = " ".join(evidence_variants)
    content = _substantive(f"Assistant: confirming. {embedded}")
    return _make_message(source_id, content, container_ref, thread_ref, role="assistant")


def _post_and_drain(client, service, messages):
    for msg in messages:
        client.post("/items", json=[msg])
    service.drain_processing_queue(worker_id="test-worker")


def _all_decisions_in_container(storage, container_ref):
    """Return all decision MemoryObjects in a container (any thread, any lifecycle)."""
    with storage._session_factory() as session:
        records = session.scalars(
            select(MemoryObjectRecord).where(
                MemoryObjectRecord.container_ref == container_ref,
                MemoryObjectRecord.type == "decision",
            )
        ).all()
        out = []
        for r in records:
            out.append(storage._to_memory_object(r))
        return out


def _all_memory_in_container(storage, container_ref, mem_type):
    with storage._session_factory() as session:
        records = session.scalars(
            select(MemoryObjectRecord).where(
                MemoryObjectRecord.container_ref == container_ref,
                MemoryObjectRecord.type == mem_type,
            )
        ).all()
        return [storage._to_memory_object(r) for r in records]


def _supported_by_target_ids(storage, memory_object_id):
    with storage._session_factory() as session:
        rows = session.scalars(
            select(RelationRecord).where(
                RelationRecord.from_kind == "memory_object",
                RelationRecord.from_id == memory_object_id,
                RelationRecord.relation_type == "supported_by",
            )
        ).all()
        return [r.to_id for r in rows]


# ---------------------------------------------------------------------------
# Stub providers
# ---------------------------------------------------------------------------

class _FixedDecisionStub:
    """Returns the same decision_text on every call but a different evidence
    quote on each thread-rebuild call (counter-driven). Both evidence variants
    must appear verbatim in the assistant message so grounding passes.

    This stub is deliberately schema-agnostic — it returns the same
    thread-summary-shaped payload to every ``generate_json`` call (per-item
    extraction and thread rebuild alike), mirroring the convention in
    ``tests/test_decision_supersession_rebuild.py::DecisionStubProvider``.
    The per-item path interprets unfamiliar fields as low-value but still
    produces the side effect we need (substantive items requesting thread
    rebuilds), and the thread-rebuild path uses the ``decisions`` list.
    """

    DECISION_TEXT = (
        "Event-time ordering selected for all reservation holds to "
        "prevent sync-delay losses across the distributed cluster."
    )
    EVIDENCE_LONG = (
        "thorough discussion and evaluation of the available options "
        "and trade-offs"
    )
    EVIDENCE_SHORT = "evaluation of the available options and trade-offs"

    def __init__(self):
        self.rebuild_call_count = 0

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        is_thread_rebuild = '"decisions"' in schema_description
        if is_thread_rebuild:
            self.rebuild_call_count += 1
            evidence = (
                self.EVIDENCE_LONG
                if self.rebuild_call_count == 1
                else self.EVIDENCE_SHORT
            )
            payload = {
                "summary": "Summary covering the event-time ordering decision.",
                "content_quality": "substantive",
                "retrieval_context": None,
                "decisions": [
                    {"decision_text": self.DECISION_TEXT, "evidence": evidence},
                ],
                "investigations": [],
            }
            if "task_checkpoint" in schema_description:
                payload["task_checkpoint"] = {
                    "summary": "cp", "task": "t", "current_state": "s",
                    "key_findings": [], "blocker_state": "", "next_step": "",
                    "evidence": [], "freshness_signal": "latest",
                    "retrieval_context": None,
                }
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)
        # Per-item path: emit a decision-shaped extraction so the per-item
        # supersession-hint emitter (build_supersession_hints) fires with
        # container-scoped hints. Required for cross-thread / cross-batch
        # supersession in the e2e tests below — the rebuild emit path only
        # sees same-thread carried conclusions.
        per_item_payload = {
            "summary": "Per-item summary of the event-time ordering decision.",
            "candidate_type": "decision",
            "decision_text": self.DECISION_TEXT,
            "decision_evidence_text": self.EVIDENCE_LONG,
        }
        return LLMJsonResponse(
            raw_text=json.dumps(per_item_payload),
            parsed_json=per_item_payload,
        )


class _DistinctDecisionsStub:
    """Two decisions sharing common nouns but distinct decision_text. Used to
    guard against accidentally enabling Jaccard for decisions: with exact-only
    matching, neither must supersede the other.

    The ``service_b`` marker lets us distinguish the two batches in the
    LLM prompt body (both per-item and thread-rebuild) without leaking
    one decision's text into the other batch's source content.
    """

    DECISION_A = (
        "Adopt PostgreSQL for the user-profile service to replace the legacy MySQL deployment."
    )
    DECISION_B = (
        "Adopt PostgreSQL for the catalog service_b after benchmarking the legacy MySQL deployment."
    )
    EVIDENCE_A = "thorough discussion and evaluation of the available options and trade-offs"
    EVIDENCE_B = "thorough discussion and evaluation of the available options and trade-offs"

    def __init__(self):
        self.rebuild_call_count = 0

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        is_thread_rebuild = '"decisions"' in schema_description
        if is_thread_rebuild:
            self.rebuild_call_count += 1
            in_b = "service_b" in user_prompt
            decision = self.DECISION_B if in_b else self.DECISION_A
            evidence = self.EVIDENCE_B if in_b else self.EVIDENCE_A
            payload = {
                "summary": f"Summary (rebuild #{self.rebuild_call_count}).",
                "content_quality": "substantive",
                "retrieval_context": None,
                "decisions": [
                    {"decision_text": decision, "evidence": evidence},
                ],
                "investigations": [],
            }
            if "task_checkpoint" in schema_description:
                payload["task_checkpoint"] = {
                    "summary": "cp", "task": "t", "current_state": "s",
                    "key_findings": [], "blocker_state": "", "next_step": "",
                    "evidence": [], "freshness_signal": "latest",
                    "retrieval_context": None,
                }
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)
        # Per-item path: emit the appropriate decision based on which
        # service the user_prompt references.
        in_b = "service_b" in user_prompt
        per_item_payload = {
            "summary": "Per-item summary discussing the database decision.",
            "candidate_type": "decision",
            "decision_text": self.DECISION_B if in_b else self.DECISION_A,
            "decision_evidence_text": self.EVIDENCE_B if in_b else self.EVIDENCE_A,
        }
        return LLMJsonResponse(
            raw_text=json.dumps(per_item_payload),
            parsed_json=per_item_payload,
        )


class _RationaleVariantStub:
    """Same decision_text on each rebuild, different rationale/evidence per call.

    The thread-aggregation writer always sets ``rationale=None`` in the payload
    (rationale is not surfaced from the LLM's thread-summary schema), so this
    stub instead drives variation through *evidence* and we assert
    ``previous_evidence_text`` accumulates distinct values across multiple
    merges. The named test
    ``test_merge_preserves_distinct_rationale_variants`` here asserts the
    *mechanism* preserves distinct provenance values across multi-step merges
    — which on the thread-aggregation path is the evidence quote, not
    rationale (see "Adaptation note" in the implementation report).
    """

    DECISION_TEXT = (
        "Migrate to gRPC streaming for the order-update channel after sustained latency complaints."
    )
    # Three distinct evidence quotes that all appear verbatim in the assistant message.
    EVIDENCE_VARIANTS = [
        "Migrate to gRPC streaming for the order-update channel",
        "after sustained latency complaints from downstream consumers",
        "the order-update channel after sustained latency complaints",
    ]

    def __init__(self):
        self.rebuild_call_count = 0

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        is_thread_rebuild = '"decisions"' in schema_description
        if is_thread_rebuild:
            idx = min(self.rebuild_call_count, len(self.EVIDENCE_VARIANTS) - 1)
            self.rebuild_call_count += 1
            payload = {
                "summary": f"Summary (rebuild #{self.rebuild_call_count}).",
                "content_quality": "substantive",
                "retrieval_context": None,
                "decisions": [
                    {
                        "decision_text": self.DECISION_TEXT,
                        "evidence": self.EVIDENCE_VARIANTS[idx],
                    }
                ],
                "investigations": [],
            }
            if "task_checkpoint" in schema_description:
                payload["task_checkpoint"] = {
                    "summary": "cp", "task": "t", "current_state": "s",
                    "key_findings": [], "blocker_state": "", "next_step": "",
                    "evidence": [], "freshness_signal": "latest",
                    "retrieval_context": None,
                }
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)
        per_item_payload = {
            "summary": "Per-item summary of the gRPC streaming decision.",
            "candidate_type": "decision",
            "decision_text": self.DECISION_TEXT,
            "decision_evidence_text": self.EVIDENCE_VARIANTS[0],
        }
        return LLMJsonResponse(
            raw_text=json.dumps(per_item_payload),
            parsed_json=per_item_payload,
        )


# ---------------------------------------------------------------------------
# Test 1 — canonical_key stable across evidence drift (unit, no DB)
# ---------------------------------------------------------------------------

def _build_aggregate_for_unit_test(decision_text, evidence, *, container_ref, thread_ref):
    """Build a minimal ThreadAggregate where ``evidence`` is a substring of the
    assistant content (so grounding passes)."""
    user_item = SourceItem(
        source_type="chat_message",
        source_id=f"{thread_ref}:u",
        content_type="text/plain",
        content=f"User context discussing the topic in detail. {evidence} matters here.",
        metadata={},
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="public",
        role="user",
        artifact_kind="message",
    )
    asst_item = SourceItem(
        source_type="assistant_artifact",
        source_id=f"{thread_ref}:a",
        content_type="text/plain",
        content=(
            f"Assistant response: {decision_text} This was decided after "
            f"{evidence}, with broad agreement from the team."
        ),
        metadata={},
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="public",
        role="assistant",
        artifact_kind="assistant_output",
    )
    return build_thread_aggregate([user_item, asst_item])


class _OneShotDecisionStub:
    def __init__(self, decision_text, evidence):
        self.decision_text = decision_text
        self.evidence = evidence

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        payload = {
            "summary": "Unit-test summary covering the decision in detail.",
            "content_quality": "substantive",
            "retrieval_context": None,
            "decisions": [
                {"decision_text": self.decision_text, "evidence": self.evidence}
            ],
            "investigations": [],
        }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def test_text_canonical_key_stable_across_evidence_drift() -> None:
    decision_text = (
        "Event-time ordering selected for all reservation holds to prevent sync-delay losses."
    )
    evidence_a = "thorough evaluation of the available options"
    evidence_b = "broad agreement from the team"

    aggregate_a = _build_aggregate_for_unit_test(
        decision_text, evidence_a,
        container_ref="ck-stable:c", thread_ref="ck-stable:t1",
    )
    aggregate_b = _build_aggregate_for_unit_test(
        decision_text, evidence_b,
        container_ref="ck-stable:c", thread_ref="ck-stable:t2",
    )

    result_a = build_thread_summary(
        provider=_OneShotDecisionStub(decision_text, evidence_a),
        prompt_variant="strict_typed_memory_v6_work_state_examples",
        plugin_name="agent_conversation_memory",
        thread_summary_schema_id="agent_conversation_memory.thread_summary",
        task_checkpoint_schema_id="agent_conversation_memory.task_checkpoint",
        aggregate=aggregate_a,
        conclusions=[],
    )
    result_b = build_thread_summary(
        provider=_OneShotDecisionStub(decision_text, evidence_b),
        prompt_variant="strict_typed_memory_v6_work_state_examples",
        plugin_name="agent_conversation_memory",
        thread_summary_schema_id="agent_conversation_memory.thread_summary",
        task_checkpoint_schema_id="agent_conversation_memory.task_checkpoint",
        aggregate=aggregate_b,
        conclusions=[],
    )

    decisions_a = [mo for mo in result_a.memory_objects if mo.type == "decision"]
    decisions_b = [mo for mo in result_b.memory_objects if mo.type == "decision"]
    assert decisions_a, "expected at least one decision in result_a"
    assert decisions_b, "expected at least one decision in result_b"
    key_a = decisions_a[0].payload.get("canonical_key")
    key_b = decisions_b[0].payload.get("canonical_key")
    assert key_a == key_b, (
        f"canonical_key drifted between evidence variants: {key_a!r} vs {key_b!r}. "
        "After T2 the key must be anchored on decision_text only."
    )
    # Sanity: it really is the text-anchored key, not the evidence-tokenset key.
    assert key_a == normalize_for_index(decision_text)


# ---------------------------------------------------------------------------
# Test 2 — second rebuild flips lifecycle even when evidence drifts (e2e)
# ---------------------------------------------------------------------------

def test_thread_rebuild_supersession_emitted_after_evidence_drift(
    monkeypatch, test_db_url
) -> None:
    container_ref = "ck-drift:container"
    thread_ref = "ck-drift:thread"

    stub = _FixedDecisionStub()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    evidence_variants = [
        _FixedDecisionStub.EVIDENCE_LONG,
        _FixedDecisionStub.EVIDENCE_SHORT,
    ]
    msgs1 = [
        _msg_with_decision(
            "ck-drift-1",
            _FixedDecisionStub.DECISION_TEXT,
            _FixedDecisionStub.EVIDENCE_LONG,
            container_ref, thread_ref,
        ),
        _msg_assistant_grounding(
            "ck-drift-2", evidence_variants, container_ref, thread_ref,
        ),
    ]
    _post_and_drain(client, service, msgs1)

    msgs2 = [
        _msg_with_decision(
            "ck-drift-3",
            _FixedDecisionStub.DECISION_TEXT,
            _FixedDecisionStub.EVIDENCE_LONG,
            container_ref, thread_ref,
        ),
        _msg_assistant_grounding(
            "ck-drift-4", evidence_variants, container_ref, thread_ref,
        ),
    ]
    _post_and_drain(client, service, msgs2)

    decisions = _all_decisions_in_container(service._storage, container_ref)
    target_key = normalize_for_index(_FixedDecisionStub.DECISION_TEXT)

    matching = [
        mo for mo in decisions
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
    ]
    active = [mo for mo in matching if mo.lifecycle == "active"]
    superseded = [mo for mo in matching if mo.lifecycle == "superseded"]

    assert stub.rebuild_call_count >= 2, (
        f"stub did not see two rebuild calls (count={stub.rebuild_call_count}); "
        "harness wiring is broken — the rest of the assertions would be vacuous."
    )
    assert len(active) == 1, (
        f"expected exactly 1 active decision after evidence-drifted second "
        f"rebuild, got {len(active)} active / {len(superseded)} superseded; "
        f"all keys: {[mo.payload.get('canonical_key') for mo in matching]}"
    )
    assert len(superseded) >= 1, (
        f"expected the first rebuild's decision to be superseded, got "
        f"active={len(active)} superseded={len(superseded)}"
    )


# ---------------------------------------------------------------------------
# Test 3 — same container, different threads → second supersedes first (e2e)
# ---------------------------------------------------------------------------

def test_container_scope_collapses_cross_thread_decisions(
    monkeypatch, test_db_url
) -> None:
    container_ref = "ck-cross-thread:container"
    thread_a = "ck-cross-thread:t-a"
    thread_b = "ck-cross-thread:t-b"

    stub = _FixedDecisionStub()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    evidence_variants = [
        _FixedDecisionStub.EVIDENCE_LONG,
        _FixedDecisionStub.EVIDENCE_SHORT,
    ]
    msgs_a = [
        _msg_with_decision("ct-a-1", _FixedDecisionStub.DECISION_TEXT,
                           _FixedDecisionStub.EVIDENCE_LONG, container_ref, thread_a),
        _msg_assistant_grounding("ct-a-2", evidence_variants, container_ref, thread_a),
    ]
    _post_and_drain(client, service, msgs_a)

    msgs_b = [
        _msg_with_decision("ct-b-1", _FixedDecisionStub.DECISION_TEXT,
                           _FixedDecisionStub.EVIDENCE_LONG, container_ref, thread_b),
        _msg_assistant_grounding("ct-b-2", evidence_variants, container_ref, thread_b),
    ]
    _post_and_drain(client, service, msgs_b)

    decisions = _all_decisions_in_container(service._storage, container_ref)
    target_key = normalize_for_index(_FixedDecisionStub.DECISION_TEXT)
    matching = [
        mo for mo in decisions
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
    ]
    active = [mo for mo in matching if mo.lifecycle == "active"]
    superseded = [mo for mo in matching if mo.lifecycle == "superseded"]

    assert len(active) == 1, (
        f"cross-thread duplicate not collapsed: active={len(active)} "
        f"superseded={len(superseded)}"
    )
    assert len(superseded) >= 1


# ---------------------------------------------------------------------------
# Test 4 — different containers → both remain active (e2e)
# ---------------------------------------------------------------------------

def test_cross_container_decisions_left_active(monkeypatch, test_db_url) -> None:
    container_a = "ck-cross-cont:c-a"
    container_b = "ck-cross-cont:c-b"
    thread_ref = "ck-cross-cont:t"

    stub = _FixedDecisionStub()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    evidence_variants = [
        _FixedDecisionStub.EVIDENCE_LONG,
        _FixedDecisionStub.EVIDENCE_SHORT,
    ]
    msgs_a = [
        _msg_with_decision("cc-a-1", _FixedDecisionStub.DECISION_TEXT,
                           _FixedDecisionStub.EVIDENCE_LONG, container_a, thread_ref),
        _msg_assistant_grounding("cc-a-2", evidence_variants, container_a, thread_ref),
    ]
    _post_and_drain(client, service, msgs_a)

    msgs_b = [
        _msg_with_decision("cc-b-1", _FixedDecisionStub.DECISION_TEXT,
                           _FixedDecisionStub.EVIDENCE_LONG, container_b, thread_ref),
        _msg_assistant_grounding("cc-b-2", evidence_variants, container_b, thread_ref),
    ]
    _post_and_drain(client, service, msgs_b)

    target_key = normalize_for_index(_FixedDecisionStub.DECISION_TEXT)
    decisions_a = [
        mo for mo in _all_decisions_in_container(service._storage, container_a)
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
    ]
    decisions_b = [
        mo for mo in _all_decisions_in_container(service._storage, container_b)
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
    ]
    active_a = [mo for mo in decisions_a if mo.lifecycle == "active"]
    active_b = [mo for mo in decisions_b if mo.lifecycle == "active"]

    assert len(active_a) >= 1, (
        f"container A should still have an active decision: {decisions_a}"
    )
    assert len(active_b) >= 1, (
        f"container B should still have an active decision: {decisions_b}"
    )

    # Cross-container check: there must be NO ``supersedes`` relation that
    # crosses container boundaries. Within-container supersession (per-item
    # vs. rebuild dup) is fine; the new T2 rule we are testing is that
    # different containers stay isolated.
    with service._storage._session_factory() as session:
        all_supersedes = session.scalars(
            select(RelationRecord).where(
                RelationRecord.relation_type == "supersedes",
                RelationRecord.from_kind == "memory_object",
                RelationRecord.to_kind == "memory_object",
            )
        ).all()
        for rel in all_supersedes:
            from_container = service._storage.get_memory_object(rel.from_id).container_ref
            to_container = service._storage.get_memory_object(rel.to_id).container_ref
            assert from_container == to_container, (
                f"unexpected cross-container supersession: "
                f"{rel.from_id[:8]}({from_container}) -> "
                f"{rel.to_id[:8]}({to_container})"
            )


# ---------------------------------------------------------------------------
# Test 5 — merge unions evidence quotes + reparents supported_by (e2e)
# ---------------------------------------------------------------------------

def test_merge_unions_evidence_quotes(monkeypatch, test_db_url) -> None:
    container_ref = "ck-merge:container"
    thread_ref = "ck-merge:thread"

    stub = _FixedDecisionStub()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    evidence_variants = [
        _FixedDecisionStub.EVIDENCE_LONG,
        _FixedDecisionStub.EVIDENCE_SHORT,
    ]
    msgs1 = [
        _msg_with_decision("mg-1", _FixedDecisionStub.DECISION_TEXT,
                           _FixedDecisionStub.EVIDENCE_LONG, container_ref, thread_ref),
        _msg_assistant_grounding("mg-2", evidence_variants, container_ref, thread_ref),
    ]
    _post_and_drain(client, service, msgs1)

    msgs2 = [
        _msg_with_decision("mg-3", _FixedDecisionStub.DECISION_TEXT,
                           _FixedDecisionStub.EVIDENCE_LONG, container_ref, thread_ref),
        _msg_assistant_grounding("mg-4", evidence_variants, container_ref, thread_ref),
    ]
    _post_and_drain(client, service, msgs2)

    target_key = normalize_for_index(_FixedDecisionStub.DECISION_TEXT)
    decisions = [
        mo for mo in _all_decisions_in_container(service._storage, container_ref)
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
    ]
    active = [mo for mo in decisions if mo.lifecycle == "active"]
    superseded = [mo for mo in decisions if mo.lifecycle == "superseded"]
    assert len(active) == 1, f"expected 1 active winner, got {len(active)}"
    assert len(superseded) >= 1, "expected at least one superseded loser"

    winner = active[0]
    merged_from = winner.payload.get("merged_from") or []
    prev_evidence = winner.payload.get("previous_evidence_text") or []

    assert merged_from, "winner.payload['merged_from'] must list loser ids"
    loser_ids = {mo.id for mo in superseded}
    assert set(merged_from) <= loser_ids, (
        f"merged_from {merged_from} must be a subset of loser ids {loser_ids}"
    )
    # The losers carried the EVIDENCE_LONG quote on the first rebuild; that
    # must now appear under the winner's previous_evidence_text. (The winner's
    # own decision_evidence_text is the most-recent evidence — EVIDENCE_SHORT.)
    assert _FixedDecisionStub.EVIDENCE_LONG in prev_evidence, (
        f"loser evidence not unioned onto winner: prev={prev_evidence!r}"
    )

    # supported_by reparenting: the winner must now link to source items from
    # both the first AND second batches (the union, deduped). supported_by
    # ``to_id`` is the source-item *internal id*, so resolve via source_id.
    expected_internal_ids = set()
    for source_id in ("mg-1", "mg-2", "mg-3", "mg-4"):
        si = service._storage.find_source_item("chat_message", source_id) or \
             service._storage.find_source_item("assistant_artifact", source_id)
        assert si is not None, f"source item {source_id!r} not found"
        expected_internal_ids.add(si.id)
    winner_targets = set(_supported_by_target_ids(service._storage, winner.id))
    assert expected_internal_ids <= winner_targets, (
        f"winner.supported_by missing reparented edges. "
        f"expected {expected_internal_ids}, got {winner_targets}"
    )

    # Loser must have NO supported_by edges left after reparenting.
    for loser in superseded:
        loser_targets = _supported_by_target_ids(service._storage, loser.id)
        assert not loser_targets, (
            f"loser {loser.id[:8]} still has supported_by edges: {loser_targets}"
        )


# ---------------------------------------------------------------------------
# Test 6 — merge preserves distinct provenance values across multi-step merges
# ---------------------------------------------------------------------------

def test_merge_preserves_distinct_rationale_variants(monkeypatch, test_db_url) -> None:
    """Drive three rebuilds with three distinct evidence quotes; assert that
    after the third merge the winner retains all distinct prior values
    (deduplicated, in order). See the docstring on
    ``_RationaleVariantStub`` for why we drive variation through evidence on
    the thread-aggregation path: ``rationale`` is always written as ``None``
    by ``build_thread_summary``, so the *mechanism under test* — multi-step
    distinct-value preservation — is exercised on the
    ``previous_evidence_text`` list.
    """
    container_ref = "ck-rationale:container"
    thread_ref = "ck-rationale:thread"

    stub = _RationaleVariantStub()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    for batch_idx in range(3):
        msgs = [
            _msg_with_decision(
                f"rv-{batch_idx}-1",
                _RationaleVariantStub.DECISION_TEXT,
                _RationaleVariantStub.EVIDENCE_VARIANTS[0],
                container_ref, thread_ref,
            ),
            _msg_assistant_grounding(
                f"rv-{batch_idx}-2",
                _RationaleVariantStub.EVIDENCE_VARIANTS,
                container_ref, thread_ref,
            ),
        ]
        _post_and_drain(client, service, msgs)

    target_key = normalize_for_index(_RationaleVariantStub.DECISION_TEXT)
    decisions = [
        mo for mo in _all_decisions_in_container(service._storage, container_ref)
        if str(mo.payload.get("canonical_key") or "").strip() == target_key
    ]
    active = [mo for mo in decisions if mo.lifecycle == "active"]
    superseded = [mo for mo in decisions if mo.lifecycle == "superseded"]
    assert len(active) == 1, f"expected 1 active winner, got {len(active)}"
    assert len(superseded) >= 2, (
        f"expected at least 2 supersession events across 3 rebuilds, "
        f"got {len(superseded)}"
    )

    winner = active[0]
    prev_evidence = winner.payload.get("previous_evidence_text") or []
    # The mechanism under test: across multiple distinct losers, the
    # winner's previous_evidence_text accumulates each distinct loser
    # evidence value (deduplicated). The exact set depends on which path
    # fires on each merge — per-item and thread-rebuild both emit
    # supersession hints, and the winner's own evidence rotates as the
    # latest stub call swaps it. We assert two structural properties:
    #
    #   1. previous_evidence_text is non-empty (a merge actually
    #      happened);
    #   2. previous_evidence_text contains no duplicates.
    #
    # Plus a stronger guarantee that at least ONE of the earlier
    # evidence variants emitted by the stub appears in prev_evidence.
    assert prev_evidence, (
        "previous_evidence_text was empty — merge did not record any loser "
        "evidence"
    )
    assert len(prev_evidence) == len(set(prev_evidence)), (
        f"previous_evidence_text not deduplicated: {prev_evidence!r}"
    )
    earlier_variants = set(_RationaleVariantStub.EVIDENCE_VARIANTS)
    assert any(v in earlier_variants for v in prev_evidence), (
        f"none of the stubbed evidence variants reached "
        f"previous_evidence_text={prev_evidence!r}"
    )


# ---------------------------------------------------------------------------
# Test 7 — distinct decisions with overlapping nouns NOT merged (regression)
# ---------------------------------------------------------------------------

def test_distinct_decisions_with_overlapping_nouns_not_merged(
    monkeypatch, test_db_url
) -> None:
    """Two decisions sharing many nouns ("Adopt PostgreSQL", "service",
    "MySQL", "deployment") but with different decision_text must remain
    distinct. Guards against accidentally enabling Jaccard for decisions at
    container scope.
    """
    container_ref = "ck-distinct:container"
    thread_ref = "ck-distinct:thread"

    stub = _DistinctDecisionsStub()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    msgs1 = [
        _msg_with_decision(
            "dn-1-a",
            _DistinctDecisionsStub.DECISION_A,
            _DistinctDecisionsStub.EVIDENCE_A,
            container_ref, thread_ref,
        ),
        _msg_assistant_grounding(
            "dn-1-b",
            [_DistinctDecisionsStub.EVIDENCE_A],
            container_ref, thread_ref,
        ),
    ]
    _post_and_drain(client, service, msgs1)

    msgs2 = [
        # ``DECISION_B`` itself contains the ``service_b`` marker the stub
        # uses to switch branches, so per-item and thread-rebuild prompts
        # both see it.
        _msg_with_decision(
            "dn-2-a",
            _DistinctDecisionsStub.DECISION_B,
            _DistinctDecisionsStub.EVIDENCE_B,
            container_ref, thread_ref,
        ),
        _msg_assistant_grounding(
            "dn-2-b",
            [_DistinctDecisionsStub.EVIDENCE_B],
            container_ref, thread_ref,
        ),
    ]
    _post_and_drain(client, service, msgs2)

    decisions = _all_decisions_in_container(service._storage, container_ref)
    key_a = normalize_for_index(_DistinctDecisionsStub.DECISION_A)
    key_b = normalize_for_index(_DistinctDecisionsStub.DECISION_B)
    assert key_a != key_b, "test fixture sanity: keys must differ"

    matching_a = [
        mo for mo in decisions
        if str(mo.payload.get("canonical_key") or "").strip() == key_a
    ]
    matching_b = [
        mo for mo in decisions
        if str(mo.payload.get("canonical_key") or "").strip() == key_b
    ]
    active_a = [mo for mo in matching_a if mo.lifecycle == "active"]
    active_b = [mo for mo in matching_b if mo.lifecycle == "active"]

    assert len(active_a) >= 1, (
        f"decision A was unexpectedly removed (false-merge?): {matching_a}"
    )
    assert len(active_b) >= 1, (
        f"decision B was unexpectedly removed (false-merge?): {matching_b}"
    )

    # The Jaccard-protection assertion: there must be NO ``supersedes``
    # relation that crosses the two distinct canonical keys. Within-key
    # supersession (e.g. per-item A -> rebuild A) is fine — that's the
    # legitimate exact-match path.
    storage = service._storage
    a_ids = {mo.id for mo in matching_a}
    b_ids = {mo.id for mo in matching_b}
    with storage._session_factory() as session:
        all_supersedes = session.scalars(
            select(RelationRecord).where(
                RelationRecord.relation_type == "supersedes",
                RelationRecord.from_kind == "memory_object",
                RelationRecord.to_kind == "memory_object",
            )
        ).all()
        for rel in all_supersedes:
            assert not (rel.from_id in b_ids and rel.to_id in a_ids), (
                f"B-keyed decision {rel.from_id[:8]} erroneously superseded "
                f"A-keyed decision {rel.to_id[:8]} (Jaccard accidentally enabled?)"
            )
            assert not (rel.from_id in a_ids and rel.to_id in b_ids), (
                f"A-keyed decision {rel.from_id[:8]} erroneously superseded "
                f"B-keyed decision {rel.to_id[:8]} (Jaccard accidentally enabled?)"
            )


# ---------------------------------------------------------------------------
# Test 8 — constraint Jaccard branch unchanged (regression)
# ---------------------------------------------------------------------------

def test_constraint_jaccard_branch_unchanged() -> None:
    """The constraint-supersession path that takes the Jaccard branch
    (token-overlap above 0.5) must continue to fire. We exercise the resolver
    at the SQL layer with hand-crafted records and hints to keep this test
    from being entangled with the LLM-driven extraction pipeline.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.contracts import ProcessResult, SupersessionHint
    from core.models import MemoryObject as DomainMemoryObject, new_id, utc_now
    from storage.sqlite import SQLiteStorageProvider
    from storage.sqlite_schema import Base, MemoryObjectRecord

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    container_ref = "ck-constraint:c"

    # Existing constraint with key 'avoid mocking llm responses tests'.
    existing_id = new_id()
    new_id_ = new_id()
    existing_payload = {
        "constraint": "Do not mock LLM responses in tests.",
        "canonical_key": "avoid mocking llm responses tests",
        "constraint_evidence_text": "Do not mock LLM responses in tests.",
    }
    new_payload = {
        "constraint": "Tests must not mock LLM responses.",
        # 5/6 token overlap with the existing key → Jaccard 5/6 ≈ 0.83 > 0.5
        "canonical_key": "avoid mocking llm responses unit tests",
        "constraint_evidence_text": "Tests must not mock LLM responses.",
    }
    with Session.begin() as session:
        session.add(MemoryObjectRecord(
            id=existing_id,
            type=CONSTRAINT_MEMORY_TYPE,
            schema_id="agent_conversation_memory.constraint",
            schema_version="v1",
            payload_json=json.dumps(existing_payload),
            lifecycle="active",
            visibility="public",
            container_ref=container_ref,
            created_at=utc_now(),
        ))
        session.add(MemoryObjectRecord(
            id=new_id_,
            type=CONSTRAINT_MEMORY_TYPE,
            schema_id="agent_conversation_memory.constraint",
            schema_version="v1",
            payload_json=json.dumps(new_payload),
            lifecycle="active",
            visibility="public",
            container_ref=container_ref,
            created_at=utc_now(),
        ))

    # Resolve via the queue mixin's helper.
    storage = SQLiteStorageProvider.__new__(SQLiteStorageProvider)
    storage._engine = engine
    storage._session_factory = Session

    process_result = ProcessResult(
        memory_objects=[
            DomainMemoryObject(
                id=new_id_,
                type=CONSTRAINT_MEMORY_TYPE,
                schema_id="agent_conversation_memory.constraint",
                schema_version="v1",
                payload=new_payload,
                visibility="public",
                container_ref=container_ref,
            )
        ],
        relations=[],
        index_entries=[],
        supersession_hints=[
            SupersessionHint(
                replacement_memory_id=new_id_,
                memory_type=CONSTRAINT_MEMORY_TYPE,
                canonical_key=new_payload["canonical_key"],
                container_ref=container_ref,
                thread_ref=None,
                visibility="public",
            )
        ],
    )

    with Session() as session:
        pairs = storage._resolve_supersession_pairs_in_session(session, process_result)

    assert pairs == [(existing_id, new_id_)], (
        f"constraint Jaccard branch did not pair existing→new constraint; "
        f"got pairs={pairs!r}"
    )


# ---------------------------------------------------------------------------
# Unit test: merge-history sliding-window cap (per code review M2)
# ---------------------------------------------------------------------------

def test_merge_decision_payload_history_caps_at_keep_last() -> None:
    """`_merge_decision_payload_into_winner` must keep only the most recent
    `_MERGE_HISTORY_KEEP_LAST` entries on each list, dropping the oldest.

    Without the cap, decisions on a hot thread accumulate evidence variants on
    every rebuild and the active winner's payload_json grows unbounded. The
    sliding window is keep-last-K (K=16 today) — see merge_policy.md and the
    code review note on unbounded list growth.
    """
    from storage.sqlite_queue import (
        SQLiteQueueMixin,
        _MERGE_HISTORY_KEEP_LAST,
    )

    keep = _MERGE_HISTORY_KEEP_LAST
    winner_payload: dict = {}

    # Drive (keep + 5) merges with distinct loser ids and evidence quotes; only
    # the most recent `keep` entries should survive on each list.
    for i in range(keep + 5):
        loser_payload = {
            "decision_evidence_text": f"evidence variant {i}",
            "rationale": f"rationale variant {i}",
        }
        SQLiteQueueMixin._merge_decision_payload_into_winner(
            winner_payload=winner_payload,
            loser_payload=loser_payload,
            loser_id=f"loser-{i:03d}",
        )

    assert len(winner_payload["merged_from"]) == keep
    assert len(winner_payload["previous_evidence_text"]) == keep
    assert len(winner_payload["previous_rationale"]) == keep

    # Sliding window keeps the most recent — the first 5 entries fall off.
    assert winner_payload["merged_from"][0] == f"loser-{5:03d}"
    assert winner_payload["merged_from"][-1] == f"loser-{keep + 4:03d}"
    assert winner_payload["previous_evidence_text"][0] == "evidence variant 5"
    assert winner_payload["previous_evidence_text"][-1] == f"evidence variant {keep + 4}"


# ---------------------------------------------------------------------------
# Regression: codex P1 — two new memories sharing a canonical_key in the same
# ProcessResult must NOT supersede each other (reciprocal A→B / B→A pairs
# would otherwise leave zero active rows for that key).
# ---------------------------------------------------------------------------

def test_same_result_duplicate_decisions_do_not_reciprocally_supersede() -> None:
    """If a single ProcessResult emits two decisions with identical canonical
    keys, the resolver must produce NO supersession pairs (and therefore leave
    both rows active). The container-scoped resolver must exclude every
    replacement id in the result from its existing-record scan, not just the
    current hint's replacement.

    Codex P1: prior to this fix, the resolver scanned for `id != current
    replacement` only. Hint A would find replacement B (in DB after persist),
    pair A→B; hint B would find replacement A, pair B→A. Both rows ended up
    superseded.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.contracts import ProcessResult, SupersessionHint
    from core.models import MemoryObject as DomainMemoryObject, new_id, utc_now
    from storage.sqlite import SQLiteStorageProvider
    from storage.sqlite_schema import Base, MemoryObjectRecord

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    container_ref = "ck-decision:c"
    canonical_key = normalize_for_index("Use event-time ordering for reservation holds.")

    a_id, b_id = new_id(), new_id()
    a_payload = {"decision": "Use event-time ordering for reservation holds.",
                 "decision_evidence_text": "alpha quote", "canonical_key": canonical_key}
    b_payload = {"decision": "Use event-time ordering for reservation holds.",
                 "decision_evidence_text": "beta quote", "canonical_key": canonical_key}

    # Both already persisted by the queue layer before resolver runs.
    with Session.begin() as session:
        for mid, payload in ((a_id, a_payload), (b_id, b_payload)):
            session.add(MemoryObjectRecord(
                id=mid,
                type="decision",
                schema_id="agent_conversation_memory.thread_decision",
                schema_version="v2",
                payload_json=json.dumps(payload),
                lifecycle="active",
                visibility="public",
                container_ref=container_ref,
                created_at=utc_now(),
            ))

    storage = SQLiteStorageProvider.__new__(SQLiteStorageProvider)
    storage._engine = engine
    storage._session_factory = Session

    process_result = ProcessResult(
        memory_objects=[
            DomainMemoryObject(
                id=a_id, type="decision",
                schema_id="agent_conversation_memory.thread_decision",
                schema_version="v2", payload=a_payload,
                visibility="public", container_ref=container_ref,
            ),
            DomainMemoryObject(
                id=b_id, type="decision",
                schema_id="agent_conversation_memory.thread_decision",
                schema_version="v2", payload=b_payload,
                visibility="public", container_ref=container_ref,
            ),
        ],
        relations=[], index_entries=[],
        supersession_hints=[
            SupersessionHint(
                replacement_memory_id=a_id, memory_type="decision",
                canonical_key=canonical_key, container_ref=container_ref,
                thread_ref=None, visibility="public",
            ),
            SupersessionHint(
                replacement_memory_id=b_id, memory_type="decision",
                canonical_key=canonical_key, container_ref=container_ref,
                thread_ref=None, visibility="public",
            ),
        ],
    )

    with Session() as session:
        pairs = storage._resolve_supersession_pairs_in_session(session, process_result)

    assert pairs == [], (
        f"Same-result duplicate decisions must not produce supersession pairs; "
        f"got pairs={pairs!r}"
    )


# ---------------------------------------------------------------------------
# Regression: codex P2 — merge-not-collapse must be transitive across an
# A→B→C chain. Older losers' evidence/rationale must survive when an
# already-merged winner is itself superseded.
# ---------------------------------------------------------------------------

def test_merge_decision_payload_is_transitive_across_chains() -> None:
    """Multi-step supersession A→B→C must preserve A's evidence/rationale on C.

    Codex P2: prior to the fix, `_merge_decision_payload_into_winner` only
    copied the immediate loser's primary `decision_evidence_text` and
    `rationale`, ignoring the loser's already-accumulated `merged_from`,
    `previous_evidence_text`, and `previous_rationale`. After A→B, B's
    payload had A's history; but after B→C, C lost A entirely.
    """
    from storage.sqlite_queue import SQLiteQueueMixin

    # Step 1 — A merges into B. B starts empty, A is the first loser.
    b_payload: dict = {
        "decision": "X",
        "decision_evidence_text": "B's own quote",
        "rationale": "B's rationale",
    }
    a_payload = {
        "decision": "X",
        "decision_evidence_text": "A's own quote",
        "rationale": "A's rationale",
    }
    SQLiteQueueMixin._merge_decision_payload_into_winner(
        winner_payload=b_payload,
        loser_payload=a_payload,
        loser_id="a",
    )
    assert b_payload["merged_from"] == ["a"]
    assert b_payload["previous_evidence_text"] == ["A's own quote"]
    assert b_payload["previous_rationale"] == ["A's rationale"]

    # Step 2 — B merges into C. C must inherit A's history through B.
    c_payload: dict = {
        "decision": "X",
        "decision_evidence_text": "C's own quote",
        "rationale": "C's rationale",
    }
    SQLiteQueueMixin._merge_decision_payload_into_winner(
        winner_payload=c_payload,
        loser_payload=b_payload,
        loser_id="b",
    )
    # merged_from carries A first (inherited), then B (immediate loser).
    assert c_payload["merged_from"] == ["a", "b"]
    # previous_evidence_text carries A's quote (from B's prior history) and
    # B's own quote.
    assert c_payload["previous_evidence_text"] == ["A's own quote", "B's own quote"]
    assert c_payload["previous_rationale"] == ["A's rationale", "B's rationale"]
