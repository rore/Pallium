"""Regression tests for empty same-thread summaries blocking external carry-forward injection.

Root cause (fixed): _compute_thread_summary_content_quality() classified LLM-generated
"No prior context, artifacts, or conclusions were provided" and
"No response, artifacts, or conclusions were provided in the thread" summaries as
"substantive" because UNRESOLVED_SUMMARY_MARKERS lacked those phrases.
As a result, same-thread suppression treated them as qualifying local state,
blocking injection of useful prior-thread memories.

Fix: added "no prior context" and "artifacts, or conclusions were provided" to
UNRESOLVED_SUMMARY_MARKERS in agent_conversation_memory_threads.py.
"""
from __future__ import annotations

from tests.agent_conversation_memory_routing_helpers import *
from semantic.agent_conversation_memory_threads import _compute_thread_summary_content_quality


# ---------------------------------------------------------------------------
# Write-time classification regression
# ---------------------------------------------------------------------------

def test_empty_no_prior_context_summary_classified_as_unresolved() -> None:
    """LLM-phrased 'no prior context' summary must not be classified as substantive."""
    result = _compute_thread_summary_content_quality(
        "User requested a reminder about recent index rebuild work. "
        "No prior context, artifacts, or conclusions were provided in this thread.",
        [],
        [],
    )
    assert result == "unresolved", (
        f"Expected 'unresolved', got {result!r}. "
        "This text was previously misclassified as 'substantive', causing same-thread over-suppression."
    )


def test_empty_no_response_provided_summary_classified_as_unresolved() -> None:
    """LLM-phrased 'no response...were provided' summary must not be classified as substantive."""
    result = _compute_thread_summary_content_quality(
        "User asked about the latest status of the index rebuild. "
        "No response, artifacts, or conclusions were provided in the thread.",
        [],
        [],
    )
    assert result == "unresolved", (
        f"Expected 'unresolved', got {result!r}. "
        "This text was previously misclassified as 'substantive', causing same-thread over-suppression."
    )


def test_substantive_summary_still_classified_correctly() -> None:
    """Guard: a summary with real content must still be classified as substantive."""
    result = _compute_thread_summary_content_quality(
        "The index rebuild completed batch 42 after the throttle reset. "
        "Constraint: do not use the admin tool login during rebuild runs.",
        [],
        [],
    )
    assert result == "substantive", (
        f"Expected 'substantive' for a real summary, got {result!r}."
    )


# ---------------------------------------------------------------------------
# Routing regression: same-thread suppression must not fire for empty summaries
# ---------------------------------------------------------------------------

def test_same_thread_no_prior_context_summary_does_not_suppress_prior_thread_checkpoint() -> None:
    """same-thread 'no prior context' summary must not qualify as sufficient local state.

    Structure mirrors the live failure:
    - Prior thread: task_checkpoint with constraint + work fact
    - Current thread: trivial greeting + recall query
    - Current thread has an empty same-thread summary saying 'No prior context...were provided'
    - Runtime context: same_thread_continuation, session_has_sufficient_local_context=True

    Expected: injection fires and includes the prior-thread checkpoint.
    The empty same-thread summary must NOT appear in injectable_blocks.
    """
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )
    query_filters = QueryFilters(
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-recall-greeting-b",
    )
    prior_checkpoint = QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="checkpoint-rebuild-prior",
        type="task_checkpoint",
        payload={
            "summary": (
                "Index rebuild paused at batch 42 due to a throttle limit. "
                "Constraint: do not use the admin tool login during the rebuild."
            ),
            "task": "Resume catalog index rebuild.",
            "current_state": "Processed 41 batches before the throttle limit triggered.",
            "key_findings": ["Do not use the admin tool login during index rebuild runs."],
            "blocker_state": "Throttle limit hit after batch 41.",
            "next_step": "Restart the rebuild from batch 42 after the throttle window resets.",
            "evidence": ["Constraint: do not use admin tool login during index rebuild."],
            "freshness_signal": "Latest update at 2026-03-11T09:58:00Z.",
        },
        freshness_at=datetime(2026, 3, 11, 9, 58, tzinfo=timezone.utc),
        score=19,
        evidence=[],
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-rebuild-prior",
    )
    _EMPTY_SUMMARY_B = (
        "User requested a reminder about recent index rebuild work. "
        "No prior context, artifacts, or conclusions were provided in this thread."
    )
    # content_quality computed via _compute_thread_summary_content_quality as it would be at write time.
    # Post-fix: this returns 'unresolved'. Pre-fix: it returned 'substantive' (the bug).
    empty_current_thread_summary = QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="thread-summary-empty-recall-b",
        type="thread_summary",
        payload={
            "summary": _EMPTY_SUMMARY_B,
            "content_quality": _compute_thread_summary_content_quality(_EMPTY_SUMMARY_B, [], []),
            "conclusions": [],
            "selected_work_artifacts": [],
        },
        freshness_at=datetime(2026, 3, 11, 10, 5, tzinfo=timezone.utc),
        score=16,
        evidence=[],
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-recall-greeting-b",
    )
    current_query_source = QueryResultItem(
        result_kind="source_hit",
        source_item_id="source-recall-greeting-b",
        source_type="chat_message",
        source_id="msg-recall-b",
        excerpt="remind me what we had lately about the index rebuild",
        occurred_at=datetime(2026, 3, 11, 10, 4, tzinfo=timezone.utc),
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-recall-greeting-b",
        artifact_kind="message",
        role="user",
        score=14,
        evidence=[],
    )

    outcome = plugin.route_query_results(
        text="remind me what we had lately about the index rebuild",
        requested_limit=4,
        retrieval_result=RetrievalQueryResult(
            results=[prior_checkpoint, empty_current_thread_summary, current_query_source],
            trace=QueryTrace(
                query_text="remind me what we had lately about the index rebuild",
                query_tokens=("remind", "me", "what", "we", "had", "lately", "about", "the", "index", "rebuild"),
                limit=4,
                filters=query_filters,
                stages=(),
            ),
        ),
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
        ),
        include_trace=True,
    )

    assert outcome.trace is not None
    same_thread_eval = outcome.trace.routing["injection_decision"]["same_thread_context_evaluation"]
    # The empty summary must NOT qualify as sufficient local state.
    assert same_thread_eval["reason_code"] != "relevant_same_thread_local_state", (
        f"Empty 'no prior context' summary must not qualify as same-thread local state. "
        f"reason_code={same_thread_eval['reason_code']}"
    )
    assert outcome.should_inject is True, (
        f"Prior-thread checkpoint should be injected. decision_reason={outcome.decision_reason}"
    )
    injected_ids = {block.result_id for block in outcome.injectable_blocks}
    assert "memory_object:checkpoint-rebuild-prior" in injected_ids, (
        f"Prior-thread task_checkpoint must be injected. Got: {injected_ids}"
    )
    assert "memory_object:thread-summary-empty-recall-b" not in injected_ids, (
        f"Empty current-thread summary must not be injected. Got: {injected_ids}"
    )


def test_same_thread_no_response_provided_summary_does_not_suppress_prior_thread_memory() -> None:
    """same-thread 'no response...were provided' summary must not qualify as sufficient local state.

    Variant using the second empty-summary phrasing observed in the live failure:
    'No response, artifacts, or conclusions were provided in the thread.'
    """
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )
    query_filters = QueryFilters(
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-wallet-recall-c",
    )
    prior_thread_summary = QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="thread-summary-wallet-prior",
        type="thread_summary",
        payload={
            "summary": (
                "Recent catalog work focused on reservation batch filtering in the wallet module. "
                "Constraint: do not use the admin tool login during batch runs."
            ),
            "content_quality": "substantive",
            "conclusions": [
                {
                    "type": "investigation_outcome",
                    "text": "Reservation batch filtering in wallet module is the active focus.",
                }
            ],
            "selected_work_artifacts": [],
        },
        freshness_at=datetime(2026, 3, 11, 9, 55, tzinfo=timezone.utc),
        score=18,
        evidence=[],
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-wallet-prior",
    )
    _EMPTY_SUMMARY_C = (
        "User asked about the latest status of the wallet module. "
        "No response, artifacts, or conclusions were provided in the thread."
    )
    empty_current_thread_summary = QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="thread-summary-empty-wallet-c",
        type="thread_summary",
        payload={
            "summary": _EMPTY_SUMMARY_C,
            "content_quality": _compute_thread_summary_content_quality(_EMPTY_SUMMARY_C, [], []),
            "conclusions": [],
            "selected_work_artifacts": [],
        },
        freshness_at=datetime(2026, 3, 11, 10, 6, tzinfo=timezone.utc),
        score=15,
        evidence=[],
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-wallet-recall-c",
    )
    current_query_source = QueryResultItem(
        result_kind="source_hit",
        source_item_id="source-wallet-recall-c",
        source_type="chat_message",
        source_id="msg-wallet-c",
        excerpt="what is the latest we have in the wallet module",
        occurred_at=datetime(2026, 3, 11, 10, 5, tzinfo=timezone.utc),
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-wallet-recall-c",
        artifact_kind="message",
        role="user",
        score=13,
        evidence=[],
    )

    outcome = plugin.route_query_results(
        text="what is the latest we have in the wallet module",
        requested_limit=4,
        retrieval_result=RetrievalQueryResult(
            results=[prior_thread_summary, empty_current_thread_summary, current_query_source],
            trace=QueryTrace(
                query_text="what is the latest we have in the wallet module",
                query_tokens=("what", "is", "the", "latest", "we", "have", "in", "the", "wallet", "module"),
                limit=4,
                filters=query_filters,
                stages=(),
            ),
        ),
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
        ),
        include_trace=True,
    )

    assert outcome.trace is not None
    same_thread_eval = outcome.trace.routing["injection_decision"]["same_thread_context_evaluation"]
    assert same_thread_eval["reason_code"] != "relevant_same_thread_local_state", (
        f"Empty 'no response...were provided' summary must not qualify as same-thread local state. "
        f"reason_code={same_thread_eval['reason_code']}"
    )
    assert outcome.should_inject is True, (
        f"Prior-thread memory should be injected. decision_reason={outcome.decision_reason}"
    )
    injected_ids = {block.result_id for block in outcome.injectable_blocks}
    assert "memory_object:thread-summary-wallet-prior" in injected_ids, (
        f"Prior-thread thread_summary must be injected. Got: {injected_ids}"
    )
    assert "memory_object:thread-summary-empty-wallet-c" not in injected_ids, (
        f"Empty current-thread summary must not be injected. Got: {injected_ids}"
    )
