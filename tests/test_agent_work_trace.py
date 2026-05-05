"""Tests for the agent_work_trace semantic package."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from capabilities.thread_aggregation import build_thread_aggregate
from core.contracts import ProcessResult
from core.models import SourceItem, MemoryObject, new_id, utc_now
from providers.llm.base import LLMProvider, LLMJsonResponse


class StubOutcomeProvider(LLMProvider):
    """LLM provider that returns a canned outcome summary."""

    def __init__(self, outcome: str | None = "Investigated FTS retrieval. Fixed IDF weights."):
        self._outcome = outcome

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        result = {"outcome": self._outcome}
        return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)


def _make_source_item(
    *,
    content: str = "I found the bug.",
    thread_ref: str = "session-1",
    container_ref: str = "git:example.com/repo",
    metadata: dict | None = None,
) -> SourceItem:
    return SourceItem(
        source_type="claude-code",
        source_id=f"cc-{new_id()[:12]}",
        content_type="text/plain",
        content=content,
        thread_ref=thread_ref,
        container_ref=container_ref,
        visibility="private",
        metadata=metadata,
    )


def _make_trace_items(turns_data: list[dict], thread_ref: str = "session-1", container_ref: str = "git:example.com/repo") -> list[SourceItem]:
    """Create SourceItems with agent_work_trace_turn metadata."""
    items = []
    for i, turn in enumerate(turns_data):
        items.append(_make_source_item(
            content=f"Turn {i} response text.",
            thread_ref=thread_ref,
            container_ref=container_ref,
            metadata={
                "agent_work_trace_turn": turn,
                "cwd": "/home/user/project",
            },
        ))
    return items


class TestItemProcessing:
    def test_requests_rebuild_when_trace_present(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        item = _make_source_item(metadata={
            "agent_work_trace_turn": {
                "files_read": ["src/main.py"],
                "commands": [],
                "grep_patterns": [],
                "has_productive_action": False,
            }
        })
        result = plugin.process_item(item)
        assert result.thread_rebuild_requested is True
        assert result.memory_objects == []

    def test_skips_rebuild_when_no_trace(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        item = _make_source_item(metadata={})
        result = plugin.process_item(item)
        assert result.thread_rebuild_requested is False

    def test_skips_rebuild_when_metadata_none(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        item = _make_source_item(metadata=None)
        result = plugin.process_item(item)
        assert result.thread_rebuild_requested is False

    def test_parallel_processing_enabled(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        assert plugin.parallel_processing is True

    def test_rebuild_supersedes_prior(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        assert plugin.rebuild_supersedes_prior is True

    def test_memory_retention_policy(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin, TASK_TRACE_TYPE
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        policy = plugin.memory_retention_policy
        assert TASK_TRACE_TYPE in policy.working_types


class TestThreadRebuild:
    def test_produces_task_trace_memory_object(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin, TASK_TRACE_TYPE
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
            {"files_read": ["/home/user/project/src/utils.py"], "commands": [], "grep_patterns": [], "has_productive_action": True},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        assert len(result.memory_objects) == 1
        mo = result.memory_objects[0]
        assert mo.type == TASK_TRACE_TYPE
        assert mo.payload["turn_count"] == 2

    def test_exploratory_productive_split(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py", "/home/user/project/src/config.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
            {"files_read": ["/home/user/project/src/main.py", "/home/user/project/src/fix.py"], "commands": [], "grep_patterns": [], "has_productive_action": True},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert "src/main.py" in payload["exploratory_files"]
        assert "src/config.py" in payload["exploratory_files"]
        assert "src/fix.py" in payload["productive_files"]
        assert payload["first_write_action_at_turn"] == 1

    def test_path_normalization(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py", "./src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert payload["exploratory_files"].count("src/main.py") == 1

    def test_commands_split_by_exit_code(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": [], "commands": [
                {"cmd": "python -m pytest", "exit_code": 0, "output_tail": "10 passed", "failure_class": "success"},
                {"cmd": "python -m pytest tests/broken.py", "exit_code": 1, "output_tail": "FAILED", "failure_class": "test_failure"},
            ], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert "python -m pytest" in payload["commands_succeeded"]
        assert "python -m pytest tests/broken.py" in payload["commands_failed"]

    def test_outcome_included_when_present(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider(outcome="Fixed the IDF bug."))
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert payload["outcome"] == "Fixed the IDF bug."
        assert payload["outcome_source"] == "llm_from_agent_responses"

    def test_outcome_absent_when_null(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider(outcome=None))
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert "outcome" not in payload
        assert payload["outcome_source"] == "none"

    def test_subject_computed_from_most_common_dir(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": [
                "/home/user/project/retrieval/lexical.py",
                "/home/user/project/retrieval/composite.py",
                "/home/user/project/retrieval/vector.py",
                "/home/user/project/storage/sqlite.py",
            ], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert payload["investigation_subject"] == "retrieval/"

    def test_index_entry_created(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        assert len(result.index_entries) == 1
        assert "src/main.py" in result.index_entries[0].text_view

    def test_no_turns_returns_empty(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = [_make_source_item(metadata={})]
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        assert result.memory_objects == []

    def test_caps_applied(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin, MAX_EXPLORATORY_FILES
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        many_files = [f"/home/user/project/src/file_{i}.py" for i in range(50)]
        items = _make_trace_items([
            {"files_read": many_files, "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert len(payload["exploratory_files"]) == MAX_EXPLORATORY_FILES

    def test_llm_failure_produces_trace_without_outcome(self):
        """LLM failure is non-blocking — trace still produced."""
        from semantic.agent_work_trace import AgentWorkTracePlugin

        class FailingProvider(LLMProvider):
            def generate_json(self, **kwargs) -> LLMJsonResponse:
                raise RuntimeError("LLM down")

        plugin = AgentWorkTracePlugin(provider=FailingProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        assert len(result.memory_objects) == 1
        assert "outcome" not in result.memory_objects[0].payload
        assert result.memory_objects[0].payload["outcome_source"] == "none"

    def test_turn_source_item_ids_populated(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/a.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
            {"files_read": ["/home/user/project/src/b.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert len(payload["turn_source_item_ids"]) == 2
        assert payload["turn_source_item_ids"][0] == items[0].id
        assert payload["turn_source_item_ids"][1] == items[1].id

    def test_all_exploratory_when_no_productive_action(self):
        """When no turn has a productive action, all files are exploratory."""
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/a.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
            {"files_read": ["/home/user/project/src/b.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert payload["first_write_action_at_turn"] is None
        assert "src/a.py" in payload["exploratory_files"]
        assert "src/b.py" in payload["exploratory_files"]
        assert payload["productive_files"] == []
