"""Thread-rebuild near-duplicate supersession fix (2026-06-28).

Bug: T2 (commit f9af592, 2026-06-04) keyed thread-aggregated
decisions/investigations on ``normalize_for_index(decision_text|
investigation_text)`` and widened supersession to container scope, but
kept exact-equality matching. LLM rebuilds that paraphrased the same
conclusion produced different canonical_keys → no supersession hint →
duplicates accumulated. Live data showed one thread with 48 active
investigation_outcome memories, 8+ paraphrases of the same conclusion.

Fix: within ``build_thread_summary``'s hint emission, walk new
decisions/investigations against prior same-thread conclusions and
emit a hint when ``SequenceMatcher.ratio`` over the canonical_keys
exceeds ``NEAR_DUP_THRESHOLD`` (0.85). The hint carries the OLD
record's canonical_key so the resolver's existing exact-equality
lookup in ``storage/sqlite_queue._resolve_supersession_pairs_in_session``
finds the old record without any resolver change.

Tests:
  1. unit (helper)         — _supersedes_prior returns expected verdicts
  2. unit (writer)         — paraphrase produces a hint targeting the
                             old record's canonical_key
  3. integration           — two thread rebuilds with paraphrased
                             investigations end with one active + one
                             superseded (NOT two active)
  4. regression (distinct) — multiple distinct findings from the same
                             thread are NOT merged

Conventions mirror ``tests/test_canonical_key_text_anchored.py``:
- real-import end-to-end through TestClient + drain for integration tests
- direct unit tests against ``build_thread_summary`` and helper

"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppConfig, LLMProviderConfig, SemanticPackageConfig
from app.main import create_app
from capabilities.consolidation import ConsolidationPolicy, DEFAULT_CONSOLIDATION_STRATEGIES
from capabilities.thread_aggregation import build_thread_aggregate
from core.models import MemoryObject, SourceItem
from providers.llm.base import LLMJsonResponse
from semantic.agent_conversation_memory_threads import (
    NEAR_DUP_THRESHOLD,
    _supersedes_prior,
    build_thread_summary,
)
from semantic.common import normalize_for_index
from storage.sqlite_schema import MemoryObjectRecord
from storage.vector_index import VectorIndexConfig


# ---------------------------------------------------------------------------
# Test 1 — unit: _supersedes_prior threshold behaviour
# ---------------------------------------------------------------------------


def _make_memory_with_ck(canonical_key: str) -> MemoryObject:
    return MemoryObject(
        type="investigation_outcome",
        schema_id="test.schema",
        schema_version="v1",
        payload={"canonical_key": canonical_key},
        container_ref="test:c",
        visibility="public",
        created_at=datetime.now(UTC),
    )


def test_supersedes_prior_returns_true_for_paraphrase_above_threshold() -> None:
    """High SequenceMatcher.ratio between two normalized texts triggers supersession."""
    # Two paraphrases of the same conclusion drawn from live-DB samples.
    new_text = normalize_for_index(
        "The Pallium session is waiting for user approval but the context-graph "
        "session is not in the same blocking state."
    )
    old_text = normalize_for_index(
        "The Pallium session is waiting for approval while the context-graph "
        "session is not in the same blocking state."
    )
    old_memory = _make_memory_with_ck(old_text)
    assert _supersedes_prior(new_text, old_memory)


def test_supersedes_prior_returns_false_for_distinct_findings() -> None:
    """Two genuinely distinct findings stay below threshold."""
    new_text = normalize_for_index(
        "Switch the order-update channel to gRPC streaming once the latency "
        "regression in HTTP polling exceeds the agreed budget on weekday peaks."
    )
    old_text = normalize_for_index(
        "Adopt Postgres logical replication for the catalog service after "
        "benchmarking against the legacy MySQL deployment over the holiday window."
    )
    old_memory = _make_memory_with_ck(old_text)
    assert not _supersedes_prior(new_text, old_memory)


def test_supersedes_prior_returns_true_for_exact_match() -> None:
    """The exact-equality fast path is preserved."""
    ck = normalize_for_index("Identical conclusion text appearing on two rebuilds.")
    old_memory = _make_memory_with_ck(ck)
    assert _supersedes_prior(ck, old_memory)


def test_supersedes_prior_returns_false_on_empty_canonical_key() -> None:
    """Empty or missing canonical_key cannot be a valid supersession target."""
    new_text = normalize_for_index("Anything.")
    old_memory = _make_memory_with_ck("")
    assert not _supersedes_prior(new_text, old_memory)
    assert not _supersedes_prior("", _make_memory_with_ck(new_text))


def test_supersedes_prior_threshold_is_0_85() -> None:
    """Document the chosen threshold inline so a change here forces a spec update."""
    assert NEAR_DUP_THRESHOLD == 0.85


# ---------------------------------------------------------------------------
# Test 2 — unit: writer emits hint with OLD canonical_key on paraphrase
# ---------------------------------------------------------------------------


class _ParaphraseInvestigationStub:
    """Returns one investigation per rebuild, with second-rebuild text being a
    paraphrase of the first."""

    FINDING_VARIANT_A = (
        "Pallium session is waiting for user approval but the context-graph "
        "session is not in the same blocking state."
    )
    FINDING_VARIANT_B = (
        "The Pallium session is waiting for approval while the context-graph "
        "session is not in the same blocking state."
    )
    EVIDENCE = "User confirmed: pallium is waiting for approval, the other is not"

    def __init__(self, variant: str):
        self._variant = variant

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        payload = {
            "summary": "Unit-test summary covering investigation outcome.",
            "content_quality": "substantive",
            "retrieval_context": None,
            "decisions": [],
            "investigations": [
                {"investigation_text": self._variant, "evidence": self.EVIDENCE},
            ],
        }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _build_aggregate_with_evidence(evidence: str, *, container_ref: str, thread_ref: str):
    user_item = SourceItem(
        source_type="chat_message",
        source_id=f"{thread_ref}:u",
        content_type="text/plain",
        content=f"User context: {evidence}. The team reviewed and discussed this carefully.",
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
            f"Assistant response: confirming. {evidence}. "
            "This was verified through subsequent observation and reporting."
        ),
        metadata={},
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="public",
        role="assistant",
        artifact_kind="assistant_output",
    )
    return build_thread_aggregate([user_item, asst_item])


def test_writer_emits_hint_with_old_canonical_key_for_paraphrase() -> None:
    """Critical resolver contract: hint.canonical_key must be the OLD record's
    canonical_key so the resolver's exact-equality lookup finds the old row.

    Builds a first-rebuild investigation, then runs a second rebuild whose
    paraphrased finding should target the first one via a hint. Asserts the
    hint's canonical_key matches the FIRST investigation's stored key.
    """
    container_ref = "ndup:unit:c"
    thread_ref = "ndup:unit:t"
    aggregate = _build_aggregate_with_evidence(
        _ParaphraseInvestigationStub.EVIDENCE,
        container_ref=container_ref,
        thread_ref=thread_ref,
    )

    # First rebuild builds an investigation with variant A.
    first = build_thread_summary(
        provider=_ParaphraseInvestigationStub(_ParaphraseInvestigationStub.FINDING_VARIANT_A),
        prompt_variant="strict_typed_memory_v6_work_state_examples",
        plugin_name="agent_conversation_memory",
        thread_summary_schema_id="agent_conversation_memory.thread_summary",
        task_checkpoint_schema_id="agent_conversation_memory.task_checkpoint",
        aggregate=aggregate,
        conclusions=[],
    )
    first_invs = [mo for mo in first.memory_objects if mo.type == "investigation_outcome"]
    assert first_invs, "first rebuild produced no investigation_outcome (test wiring broken)"
    first_inv = first_invs[0]
    old_ck = first_inv.payload["canonical_key"]

    # Second rebuild carries variant B as a paraphrase, with the first
    # investigation passed as prior conclusion.
    second = build_thread_summary(
        provider=_ParaphraseInvestigationStub(_ParaphraseInvestigationStub.FINDING_VARIANT_B),
        prompt_variant="strict_typed_memory_v6_work_state_examples",
        plugin_name="agent_conversation_memory",
        thread_summary_schema_id="agent_conversation_memory.thread_summary",
        task_checkpoint_schema_id="agent_conversation_memory.task_checkpoint",
        aggregate=aggregate,
        conclusions=[first_inv],
    )
    second_invs = [mo for mo in second.memory_objects if mo.type == "investigation_outcome"]
    assert second_invs, "second rebuild produced no investigation_outcome"
    new_inv = second_invs[0]
    new_ck = new_inv.payload["canonical_key"]

    # Sanity: the two canonical_keys actually differ (otherwise this test
    # would degenerate into the exact-match case, which is already covered).
    assert old_ck != new_ck, (
        f"canonical_keys unexpectedly equal — paraphrase fixture is too similar: "
        f"{old_ck!r}"
    )

    # The hint emission contract:
    hints_for_new = [
        hint for hint in second.supersession_hints
        if hint.replacement_memory_id == new_inv.id
    ]
    assert hints_for_new, "no supersession hint emitted for the paraphrase"
    assert any(hint.canonical_key == old_ck for hint in hints_for_new), (
        f"hint must carry the OLD record's canonical_key so the resolver's "
        f"exact-equality lookup matches. Got: "
        f"{[hint.canonical_key for hint in hints_for_new]!r} vs old_ck={old_ck!r}"
    )
    # And the hint type / container / thread_ref shape matches T2 contract.
    for hint in hints_for_new:
        assert hint.memory_type == "investigation_outcome"
        assert hint.container_ref == container_ref
        assert hint.thread_ref is None, (
            "decision/investigation_outcome hints must be container-scoped "
            "(thread_ref=None) — T2 contract from f9af592."
        )


# ---------------------------------------------------------------------------
# Integration test helpers (mirror tests/test_canonical_key_text_anchored.py)
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
    padding = (
        " The team reviewed the approach carefully and agreed on the implementation plan "
        "after thorough discussion and evaluation of the available options and trade-offs."
    )
    return base + padding


def _post_and_drain(client, service, messages):
    for msg in messages:
        client.post("/items", json=[msg])
    service.drain_processing_queue(worker_id="test-worker")


def _all_in_container(storage, container_ref: str, mtype: str):
    with storage._session_factory() as session:
        records = session.scalars(
            select(MemoryObjectRecord).where(
                MemoryObjectRecord.container_ref == container_ref,
                MemoryObjectRecord.type == mtype,
            )
        ).all()
        return [storage._to_memory_object(r) for r in records]


# ---------------------------------------------------------------------------
# Integration stub — paraphrased investigations across rebuilds
# ---------------------------------------------------------------------------


class _ParaphrasingIntegrationStub:
    """Returns paraphrased investigation_outcome text per rebuild. Both
    variants of the evidence appear in the assistant message so the
    grounding check (`_validate_thread_investigations`) passes regardless
    of which variant the stub returns.

    Schema-agnostic — returns the same shape on every ``generate_json``
    call (per-item extraction + thread rebuild alike), mirroring
    ``DecisionStubProvider`` in tests/test_decision_supersession_rebuild.py.
    Counts ``rebuild_call_count`` separately so we can pick the right
    paraphrase per thread-rebuild call.
    """

    INV_VARIANT_A = (
        "Pallium session is waiting for user approval but the context-graph "
        "session is not in the same blocking state."
    )
    INV_VARIANT_B = (
        "The Pallium session is waiting for approval while the context-graph "
        "session is not in the same blocking state."
    )
    EVIDENCE_A = "pallium is waiting for user approval and context-graph is not"
    EVIDENCE_B = "pallium waits for approval while context-graph is not"

    def __init__(self):
        self.rebuild_call_count = 0
        self.call_count = 0

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        self.call_count += 1
        is_thread_rebuild = '"investigations"' in schema_description
        if is_thread_rebuild:
            self.rebuild_call_count += 1
            inv_text = self.INV_VARIANT_A if self.rebuild_call_count == 1 else self.INV_VARIANT_B
            evidence = self.EVIDENCE_A if self.rebuild_call_count == 1 else self.EVIDENCE_B
            payload = {
                "summary": f"Summary covering session-approval finding (rebuild #{self.rebuild_call_count}).",
                "content_quality": "substantive",
                "retrieval_context": None,
                "decisions": [],
                "investigations": [
                    {"investigation_text": inv_text, "evidence": evidence},
                ],
            }
            if "task_checkpoint" in schema_description:
                payload["task_checkpoint"] = {
                    "summary": "cp", "task": "t", "current_state": "s",
                    "key_findings": [], "blocker_state": "", "next_step": "",
                    "evidence": [], "freshness_signal": "latest",
                    "retrieval_context": None,
                }
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)
        # Per-item path: emit a substantive thread-summary-shaped payload so
        # _should_request_thread_rebuild returns True. Mirrors the convention
        # in tests/test_decision_supersession_rebuild.py::DecisionStubProvider —
        # per-item handlers don't strictly need this shape, but emitting it
        # avoids any low-value classification.
        per_item_payload = {
            "summary": "Per-item summary of the session-approval finding.",
            "content_quality": "substantive",
            "retrieval_context": None,
            "decisions": [],
            "investigations": [
                {"investigation_text": self.INV_VARIANT_A, "evidence": self.EVIDENCE_A},
            ],
        }
        return LLMJsonResponse(
            raw_text=json.dumps(per_item_payload),
            parsed_json=per_item_payload,
        )


# ---------------------------------------------------------------------------
# Test 3 — integration: paraphrased investigations collapse to one active
# ---------------------------------------------------------------------------


def test_paraphrased_investigation_supersession_e2e(monkeypatch, test_db_url) -> None:
    """Two thread rebuilds producing paraphrased investigation_outcome end with
    one active + one superseded, NOT two active.

    Bug reproduced when the supersession-hint comprehension required byte-
    equality on canonical_key. Fixed by the ``_supersedes_prior`` similarity
    check (NEAR_DUP_THRESHOLD = 0.85).
    """
    container_ref = "ndup:e2e:c"
    thread_ref = "ndup:e2e:t"

    stub = _ParaphrasingIntegrationStub()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    # Assistant message embeds BOTH evidence variants verbatim so grounding
    # passes regardless of which rebuild call we're in.
    asst_content = _substantive(
        "Assistant: confirmed. "
        f"{_ParaphrasingIntegrationStub.EVIDENCE_A}. "
        f"Also: {_ParaphrasingIntegrationStub.EVIDENCE_B}."
    )

    msgs1 = [
        _make_message(
            "ndup-1",
            _substantive(
                "User: why is pallium blocked? "
                f"Context: {_ParaphrasingIntegrationStub.EVIDENCE_A}. "
                f"Also: {_ParaphrasingIntegrationStub.EVIDENCE_B}."
            ),
            container_ref, thread_ref,
        ),
        _make_message("ndup-2", asst_content, container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, msgs1)

    # Second batch with a new pair of source items triggers a second rebuild.
    msgs2 = [
        _make_message(
            "ndup-3",
            _substantive(
                "User: still confused. "
                f"Repeat: {_ParaphrasingIntegrationStub.EVIDENCE_A}. "
                f"Repeat: {_ParaphrasingIntegrationStub.EVIDENCE_B}."
            ),
            container_ref, thread_ref,
        ),
        _make_message("ndup-4", asst_content, container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, msgs2)

    assert stub.rebuild_call_count >= 2, (
        f"stub did not see two rebuild calls (count={stub.rebuild_call_count}); "
        "harness wiring is broken — the rest of the assertions would be vacuous."
    )

    invs = _all_in_container(service._storage, container_ref, "investigation_outcome")
    # Filter to the rows whose canonical_key matches one of the two variants
    # (excludes any unrelated rows produced by per-item processing on the
    # padding text).
    target_keys = {
        normalize_for_index(_ParaphrasingIntegrationStub.INV_VARIANT_A),
        normalize_for_index(_ParaphrasingIntegrationStub.INV_VARIANT_B),
    }
    relevant = [
        mo for mo in invs
        if str(mo.payload.get("canonical_key") or "").strip() in target_keys
    ]
    active = [mo for mo in relevant if mo.lifecycle == "active"]
    superseded = [mo for mo in relevant if mo.lifecycle == "superseded"]

    assert len(active) == 1, (
        f"expected exactly 1 active paraphrased investigation_outcome, "
        f"got active={len(active)} superseded={len(superseded)} "
        f"keys={[mo.payload.get('canonical_key') for mo in relevant]}"
    )
    assert len(superseded) >= 1, (
        f"expected the first rebuild's investigation_outcome to be superseded, "
        f"got active={len(active)} superseded={len(superseded)}"
    )


# ---------------------------------------------------------------------------
# Integration stub — two distinct findings produced in two rebuilds
# ---------------------------------------------------------------------------


class _DistinctFindingsStub:
    """Two genuinely distinct findings — different topics, low SequenceMatcher.ratio
    on the normalized texts. Must NOT be merged by the near-dup fix.

    Schema-agnostic shape on every call (mirrors DecisionStubProvider).
    """

    INV_A = (
        "Switch the order-update channel to gRPC streaming once the latency "
        "regression in HTTP polling exceeds the agreed budget on weekday peaks."
    )
    INV_B = (
        "Adopt Postgres logical replication for the catalog service after "
        "benchmarking against the legacy MySQL deployment over the holiday window."
    )
    EVIDENCE_A = "latency regression in HTTP polling exceeds the agreed budget"
    EVIDENCE_B = "benchmarking against the legacy MySQL deployment over the holiday window"

    def __init__(self):
        self.rebuild_call_count = 0
        self.call_count = 0

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        self.call_count += 1
        is_thread_rebuild = '"investigations"' in schema_description
        in_b = "Postgres" in user_prompt or "logical replication" in user_prompt
        inv_text = self.INV_B if in_b else self.INV_A
        evidence = self.EVIDENCE_B if in_b else self.EVIDENCE_A
        if is_thread_rebuild:
            self.rebuild_call_count += 1
            payload = {
                "summary": f"Summary (rebuild #{self.rebuild_call_count}).",
                "content_quality": "substantive",
                "retrieval_context": None,
                "decisions": [],
                "investigations": [
                    {"investigation_text": inv_text, "evidence": evidence},
                ],
            }
            if "task_checkpoint" in schema_description:
                payload["task_checkpoint"] = {
                    "summary": "cp", "task": "t", "current_state": "s",
                    "key_findings": [], "blocker_state": "", "next_step": "",
                    "evidence": [], "freshness_signal": "latest",
                    "retrieval_context": None,
                }
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)
        # Per-item path: emit a thread-summary-shaped payload so
        # _should_request_thread_rebuild treats the item as substantive.
        per_item_payload = {
            "summary": f"Per-item summary discussing the topic.",
            "content_quality": "substantive",
            "retrieval_context": None,
            "decisions": [],
            "investigations": [
                {"investigation_text": inv_text, "evidence": evidence},
            ],
        }
        return LLMJsonResponse(
            raw_text=json.dumps(per_item_payload),
            parsed_json=per_item_payload,
        )


# ---------------------------------------------------------------------------
# Test 4 — regression: distinct findings from same thread are NOT merged
# ---------------------------------------------------------------------------


def test_distinct_findings_from_same_thread_not_merged(monkeypatch, test_db_url) -> None:
    """Spec-example regression: the 48-investigation thread that motivated this
    fix contains many genuinely distinct findings. Two rebuilds producing
    different topics must end with both active.

    Guards against the Fix-B disaster path identified in the bug report:
    "one per thread, naive" would demote 349 of 404 active investigations,
    destroying legitimate distinct findings. NEAR_DUP_THRESHOLD = 0.85
    keeps them separate.
    """
    container_ref = "ndup:distinct:c"
    thread_ref = "ndup:distinct:t"

    stub = _DistinctFindingsStub()
    client, service = _create_client(monkeypatch, test_db_url, stub)

    asst_a = _substantive(
        f"Assistant: confirmed. {_DistinctFindingsStub.EVIDENCE_A}. "
        "This was verified through measurement and report."
    )
    asst_b = _substantive(
        f"Assistant: confirmed. {_DistinctFindingsStub.EVIDENCE_B}. "
        "This was verified through measurement and report."
    )

    msgs_a = [
        _make_message(
            "dist-a-1",
            _substantive(f"User context: {_DistinctFindingsStub.EVIDENCE_A}."),
            container_ref, thread_ref,
        ),
        _make_message("dist-a-2", asst_a, container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, msgs_a)

    msgs_b = [
        _make_message(
            "dist-b-1",
            _substantive(
                "User context: Postgres logical replication catalog service. "
                f"{_DistinctFindingsStub.EVIDENCE_B}."
            ),
            container_ref, thread_ref,
        ),
        _make_message("dist-b-2", asst_b, container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, msgs_b)

    assert stub.rebuild_call_count >= 2, (
        f"stub did not see two rebuild calls (count={stub.rebuild_call_count})"
    )

    invs = _all_in_container(service._storage, container_ref, "investigation_outcome")
    target_keys = {
        normalize_for_index(_DistinctFindingsStub.INV_A),
        normalize_for_index(_DistinctFindingsStub.INV_B),
    }
    relevant_active = [
        mo for mo in invs
        if mo.lifecycle == "active"
        and str(mo.payload.get("canonical_key") or "").strip() in target_keys
    ]
    keys_active = {mo.payload["canonical_key"] for mo in relevant_active}
    assert keys_active == target_keys, (
        f"both distinct findings must remain active. Got active keys={keys_active!r}, "
        f"expected={target_keys!r}. All rows: "
        f"{[(mo.payload.get('canonical_key'), mo.lifecycle) for mo in invs]}"
    )
