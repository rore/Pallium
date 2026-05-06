from __future__ import annotations

import pytest

from semantic.agent_conversation_memory_routing_selection import (
    _select_compatible_recall_candidates,
    _build_raw_injectable_block,
    MIN_SOURCE_HIT_SLOTS,
)
from core.models import QueryResultItem


def _make_task_trace_candidate(payload: dict) -> dict:
    item = QueryResultItem(
        result_kind="memory_hit",
        result_id="trace-1",
        memory_object_id="mo-trace-1",
        type="task_trace",
        payload=payload,
        score=100,
        evidence=[],
    )
    return {"item": item, "layer": "task_trace", "retrieval_score": 100, "routing_score": 100}


class TestTaskTraceCardRenderer:
    def test_area_and_outcome_in_first_line(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "retrieval/",
            "outcome": "Fixed IDF weights.",
            "exploratory_files": [],
            "commands_succeeded": [],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert block.title == "Task Trace"
        assert block.text.startswith("Area: retrieval/ — Fixed IDF weights.")

    def test_area_without_outcome(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "semantic/",
            "exploratory_files": [],
            "commands_succeeded": [],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "Area: semantic/" in block.text
        assert " — " not in block.text

    def test_explored_files_shown(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "core/",
            "exploratory_files": ["core/service.py", "core/models.py"],
            "commands_succeeded": [],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "Explored: core/service.py, core/models.py" in block.text

    def test_explored_files_capped_at_five(self):
        files = [f"src/file{i}.py" for i in range(8)]
        candidate = _make_task_trace_candidate({
            "investigation_subject": "src/",
            "exploratory_files": files,
            "commands_succeeded": [],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "[+3 more]" in block.text
        assert "file5" not in block.text

    def test_verified_with_succeeded_command(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "tests/",
            "exploratory_files": [],
            "commands_succeeded": ["python -m pytest tests/ -x -q"],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "Verified with: python -m pytest tests/ -x -q" in block.text

    def test_long_command_truncated(self):
        long_cmd = "python -m pytest tests/integration/test_very_long_path_name.py -v -x --tb=short"
        candidate = _make_task_trace_candidate({
            "investigation_subject": "tests/",
            "exploratory_files": [],
            "commands_succeeded": [long_cmd],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "Verified with: " in block.text
        verified_line = [l for l in block.text.splitlines() if l.startswith("Verified with:")][0]
        assert len(verified_line) <= len("Verified with: ") + 60

    def test_had_failures_shown_when_commands_failed(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "core/",
            "exploratory_files": [],
            "commands_succeeded": [],
            "commands_failed": ["python -m pytest tests/ -x -q"],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "Had failures" in block.text

    def test_had_failures_not_shown_when_no_failures(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "core/",
            "exploratory_files": [],
            "commands_succeeded": ["python -m pytest tests/ -x -q"],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "Had failures" not in block.text

    def test_memory_type_is_task_trace(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "core/",
            "exploratory_files": [],
            "commands_succeeded": [],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert block.memory_type == "task_trace"
        assert block.block_type == "memory"

    def test_empty_payload_produces_empty_text(self):
        candidate = _make_task_trace_candidate({})
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert block.title == "Task Trace"
        assert block.text == ""

    def test_modified_files_shown_in_card(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "retrieval/",
            "exploratory_files": ["retrieval/lexical.py"],
            "files_modified": ["retrieval/lexical.py", "tests/test_retrieval.py"],
            "commands_succeeded": [],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "Modified: retrieval/lexical.py, tests/test_retrieval.py" in block.text

    def test_modified_files_capped_at_three(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "src/",
            "exploratory_files": [],
            "files_modified": [f"src/file{i}.py" for i in range(5)],
            "commands_succeeded": [],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "[+2 more]" in block.text
        assert "file3" not in block.text

    def test_no_modified_line_when_files_modified_empty(self):
        candidate = _make_task_trace_candidate({
            "investigation_subject": "src/",
            "exploratory_files": ["src/a.py"],
            "files_modified": [],
            "commands_succeeded": [],
            "commands_failed": [],
        })
        block = _build_raw_injectable_block(candidate, intent="recall")
        assert "Modified:" not in block.text


def _make_candidate(result_kind: str, score: int, layer: str = "atomic_fact") -> dict:
    """Helper to build a routing candidate dict for testing."""
    if result_kind == "memory_hit":
        item = QueryResultItem(
            result_kind="memory_hit",
            result_id=f"mem-{score}-{id(object())}",
            memory_object_id=f"mo-{score}",
            type="atomic_fact",
            payload={"statement": f"fact {score}"},
            score=score,
            evidence=[],
        )
    else:
        item = QueryResultItem(
            result_kind="source_hit",
            result_id=f"src-{score}-{id(object())}",
            source_item_id=f"si-{score}",
            source_type="chat",
            source_id=f"s-{score}",
            excerpt=f"source content {score}",
            score=score,
            evidence=[],
        )
    return {
        "item": item,
        "layer": layer,
        "retrieval_score": score,
        "routing_score": score,
    }


def test_recall_reserves_source_hit_slots():
    """When both memory_hits and source_hits exist, source_hits get reserved slots."""
    candidates = (
        [_make_candidate("memory_hit", 100 - i) for i in range(8)]
        + [_make_candidate("source_hit", 80 - i, layer="source_evidence") for i in range(4)]
    )
    selected, _ = _select_compatible_recall_candidates(
        ranked_candidates=candidates,
        requested_limit=10,
        query_shape_tags=[],
        packaging_summary={},
    )
    source_count = sum(1 for c in selected if c["item"].result_kind == "source_hit")
    assert source_count >= MIN_SOURCE_HIT_SLOTS


def test_recall_source_reservation_respects_score_floor():
    """Source hits below 50% of primary score should not be included despite reservation."""
    candidates = (
        [_make_candidate("memory_hit", 100)]
        + [_make_candidate("source_hit", 10, layer="source_evidence")]
    )
    selected, _ = _select_compatible_recall_candidates(
        ranked_candidates=candidates,
        requested_limit=10,
        query_shape_tags=[],
        packaging_summary={},
    )
    source_count = sum(1 for c in selected if c["item"].result_kind == "source_hit")
    assert source_count == 0


def test_recall_no_source_hits_fills_with_structured():
    """When no source hits exist, all slots go to structured."""
    candidates = [_make_candidate("memory_hit", 100 - i) for i in range(8)]
    selected, _ = _select_compatible_recall_candidates(
        ranked_candidates=candidates,
        requested_limit=5,
        query_shape_tags=[],
        packaging_summary={},
    )
    assert len(selected) == 5
    assert all(c["item"].result_kind == "memory_hit" for c in selected)
