"""Tests for the task checkpoint forced injection bypass.

When a session is long (>= 12 items) and routing suppresses injection due to
same_thread_context_sufficient, the bypass loads the latest checkpoint for
the thread and injects it regardless.
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from core.contracts import PackageQueryOutcome
from core.models import (
    EvidenceReference,
    InjectableBlock,
    MemoryObject,
    QueryRuntimeContext,
)
from core.query import (
    CHECKPOINT_BYPASS_ITEM_THRESHOLD,
    QueryExecutor,
    _build_checkpoint_block,
)


def _make_memory_object(*, task="implement feature X", current_state="halfway done", next_step="add tests") -> MemoryObject:
    return MemoryObject(
        type="task_checkpoint",
        schema_id="task_checkpoint",
        schema_version="1",
        payload={
            "task": task,
            "summary": "Working on feature X",
            "current_state": current_state,
            "next_step": next_step,
            "blocker_state": "",
        },
        lifecycle="active",
        container_ref="git:test/repo",
        freshness_at=None,
    )


def _make_evidence(thread_ref: str = "thread-1") -> list[EvidenceReference]:
    return [
        EvidenceReference(
            source_item_id="si-1",
            source_type="chat_message",
            source_id="msg-1",
            thread_ref=thread_ref,
        ),
    ]


def _make_suppressed_outcome() -> PackageQueryOutcome:
    return PackageQueryOutcome(
        results=[],
        should_inject=False,
        decision_reason="same_thread_context_sufficient",
        injectable_blocks=[],
    )


class TestBuildCheckpointBlock:
    def test_builds_block_with_task_in_title(self):
        mo = _make_memory_object(task="fix the auth bug")
        evidence = _make_evidence()
        block = _build_checkpoint_block(mo, evidence)
        assert block.block_type == "memory"
        assert "fix the auth bug" in block.title
        assert block.memory_type == "task_checkpoint"
        assert block.memory_object_id == mo.id
        assert block.expand_available is True
        assert block.evidence == evidence

    def test_includes_current_state_and_next_step(self):
        mo = _make_memory_object(current_state="migrated 3/5 tables", next_step="migrate users table")
        block = _build_checkpoint_block(mo, [])
        assert "migrated 3/5 tables" in block.text
        assert "migrate users table" in block.text

    def test_uses_blocker_when_present(self):
        mo = MemoryObject(
            type="task_checkpoint",
            schema_id="task_checkpoint",
            schema_version="1",
            payload={
                "task": "deploy",
                "blocker_state": "CI pipeline failing on lint",
                "current_state": "",
                "next_step": "fix lint errors",
            },
            lifecycle="active",
        )
        block = _build_checkpoint_block(mo, [])
        assert "CI pipeline failing on lint" in block.text

    def test_empty_payload_uses_summary(self):
        mo = MemoryObject(
            type="task_checkpoint",
            schema_id="task_checkpoint",
            schema_version="1",
            payload={"task": "analyze", "summary": "analyzing performance"},
            lifecycle="active",
        )
        block = _build_checkpoint_block(mo, [])
        assert "analyzing performance" in block.text


class TestCheckpointBypass:
    def _make_executor(self, checkpoint: MemoryObject | None = None, evidence=None):
        storage = MagicMock()
        storage.find_latest_checkpoint_for_thread.return_value = checkpoint
        storage.get_evidence_for_memory_object.return_value = evidence or []
        retrieval = MagicMock()
        executor = QueryExecutor(
            storage=storage,
            retrieval=retrieval,
            semantic_plugins={},
            default_use_case="test",
        )
        return executor, storage

    def test_does_not_fire_for_non_suppressed_outcome(self):
        executor, storage = self._make_executor()
        outcome = PackageQueryOutcome(
            results=[], should_inject=True,
            decision_reason="carry_forward_available",
            injectable_blocks=[InjectableBlock(
                result_id="x", block_type="memory", title="t", text="t", evidence=[],
            )],
        )
        runtime = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=20,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=runtime,
            container_ref="c", thread_ref="t",
        )
        assert result is outcome
        storage.find_latest_checkpoint_for_thread.assert_not_called()

    def test_does_not_fire_for_short_session(self):
        executor, storage = self._make_executor()
        outcome = _make_suppressed_outcome()
        runtime = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=5,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=runtime,
            container_ref="c", thread_ref="t",
        )
        assert result.should_inject is False
        assert result.decision_reason == "same_thread_context_sufficient"
        storage.find_latest_checkpoint_for_thread.assert_not_called()

    def test_does_not_fire_when_no_checkpoint_exists(self):
        executor, storage = self._make_executor(checkpoint=None)
        outcome = _make_suppressed_outcome()
        runtime = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=20,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=runtime,
            container_ref="c", thread_ref="t",
        )
        assert result.should_inject is False
        storage.find_latest_checkpoint_for_thread.assert_called_once_with("c", "t")

    def test_fires_for_long_session_with_checkpoint(self):
        checkpoint = _make_memory_object(task="build API", next_step="add auth middleware")
        evidence = _make_evidence("t")
        executor, storage = self._make_executor(checkpoint=checkpoint, evidence=evidence)
        outcome = _make_suppressed_outcome()
        runtime = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=CHECKPOINT_BYPASS_ITEM_THRESHOLD,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=runtime,
            container_ref="c", thread_ref="t",
        )
        assert result.should_inject is True
        assert result.decision_reason == "forced_checkpoint_reinject"
        assert len(result.injectable_blocks) == 1
        block = result.injectable_blocks[0]
        assert block.memory_type == "task_checkpoint"
        assert "build API" in block.title
        assert "add auth middleware" in block.text

    def test_does_not_fire_for_empty_checkpoint_payload(self):
        checkpoint = MemoryObject(
            type="task_checkpoint",
            schema_id="task_checkpoint",
            schema_version="1",
            payload={"task": "something", "summary": "just a summary"},
            lifecycle="active",
            container_ref="c",
        )
        executor, storage = self._make_executor(checkpoint=checkpoint)
        outcome = _make_suppressed_outcome()
        runtime = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=20,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=runtime,
            container_ref="c", thread_ref="t",
        )
        assert result.should_inject is False

    def test_threshold_boundary_exact(self):
        checkpoint = _make_memory_object()
        evidence = _make_evidence()
        executor, storage = self._make_executor(checkpoint=checkpoint, evidence=evidence)
        outcome = _make_suppressed_outcome()

        just_below = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=CHECKPOINT_BYPASS_ITEM_THRESHOLD - 1,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=just_below,
            container_ref="c", thread_ref="t",
        )
        assert result.should_inject is False

        at_threshold = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=CHECKPOINT_BYPASS_ITEM_THRESHOLD,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=at_threshold,
            container_ref="c", thread_ref="t",
        )
        assert result.should_inject is True

    def test_does_not_fire_without_thread_ref(self):
        executor, storage = self._make_executor()
        outcome = _make_suppressed_outcome()
        runtime = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=20,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=runtime,
            container_ref="c", thread_ref=None,
        )
        assert result.should_inject is False
        storage.find_latest_checkpoint_for_thread.assert_not_called()

    def test_does_not_fire_without_container_ref(self):
        executor, storage = self._make_executor()
        outcome = _make_suppressed_outcome()
        runtime = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=20,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=runtime,
            container_ref=None, thread_ref="t",
        )
        assert result.should_inject is False
        storage.find_latest_checkpoint_for_thread.assert_not_called()

    def test_whitespace_only_payload_does_not_fire(self):
        checkpoint = MemoryObject(
            type="task_checkpoint",
            schema_id="task_checkpoint",
            schema_version="1",
            payload={"task": "something", "next_step": "   ", "current_state": "  ", "blocker_state": ""},
            lifecycle="active",
            container_ref="c",
        )
        executor, storage = self._make_executor(checkpoint=checkpoint)
        outcome = _make_suppressed_outcome()
        runtime = QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
            thread_item_count=20,
        )
        result = executor._checkpoint_bypass(
            outcome, runtime_context=runtime,
            container_ref="c", thread_ref="t",
        )
        assert result.should_inject is False
