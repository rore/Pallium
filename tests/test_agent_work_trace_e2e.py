"""End-to-end integration tests for the agent_work_trace pipeline.

Validates:
1. Hook-side extraction from realistic transcripts
2. Full pipeline: ingest → process → task_trace creation
3. Supersession on new turns
4. LLM failure graceful degradation
5. Lexical retrieval of task_trace
6. Edge cases: path normalization and caps
7. Regressions: normal ingest, mixed items, parallel package coexistence
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from core.models import SourceItem, new_id, utc_now
from core.service import PalliumService
from providers.llm.base import LLMProvider, LLMJsonResponse
from retrieval.lexical import LexicalRetrievalProvider
from semantic.agent_work_trace import (
    AgentWorkTracePlugin,
    TASK_TRACE_TYPE,
    TASK_TRACE_SCHEMA_ID,
    normalize_path,
    _compute_subject,
    MAX_EXPLORATORY_FILES,
    MAX_PRODUCTIVE_FILES,
    MAX_COMMANDS_SUCCEEDED,
    MAX_COMMANDS_FAILED,
)
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# Hook common.py import (standalone module, no Pallium core deps)
# ---------------------------------------------------------------------------

_cc_common_path = str(
    Path(__file__).resolve().parent.parent
    / "integrations" / "claude-code" / "hooks" / "common.py"
)
_spec = importlib.util.spec_from_file_location("cc_common_e2e", _cc_common_path)
cc_common = importlib.util.module_from_spec(_spec)
sys.modules["cc_common_e2e"] = cc_common
_spec.loader.exec_module(cc_common)


# ---------------------------------------------------------------------------
# Stub LLM providers
# ---------------------------------------------------------------------------


class StubOutcomeProvider(LLMProvider):
    """LLM provider that returns a canned outcome summary."""

    def __init__(self, outcome: str | None = "Fixed the bug in retrieval."):
        self._outcome = outcome

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str
    ) -> LLMJsonResponse:
        result = {"outcome": self._outcome}
        return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)


class FailingOutcomeProvider(LLMProvider):
    """LLM provider that always fails."""

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str
    ) -> LLMJsonResponse:
        raise RuntimeError("LLM unavailable")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def service(test_db_url):
    storage = SQLiteStorageProvider(test_db_url)
    plugins = {
        "demo_agent_memory": DemoAgentMemoryPlugin(),
        "agent_work_trace": AgentWorkTracePlugin(provider=StubOutcomeProvider()),
    }
    return PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )


@pytest.fixture
def failing_service(test_db_url):
    """Service with a failing LLM provider for outcome extraction."""
    storage = SQLiteStorageProvider(test_db_url)
    plugins = {
        "demo_agent_memory": DemoAgentMemoryPlugin(),
        "agent_work_trace": AgentWorkTracePlugin(provider=FailingOutcomeProvider()),
    }
    return PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONTAINER_REF = "git:example.com/test-repo"
THREAD_REF = "session-e2e-001"


def _ingest_trace_items(
    service: PalliumService,
    turns: list[dict],
    *,
    thread_ref: str = THREAD_REF,
    container_ref: str = CONTAINER_REF,
    cwd: str = "/home/user/project",
):
    """Ingest source items with agent_work_trace_turn metadata."""
    for i, turn in enumerate(turns):
        service.ingest_item(
            source_type="claude-code",
            source_id=f"cc-trace-{new_id()[:12]}",
            content_type="text/plain",
            content=f"Turn {i}: I analyzed the code and made changes.",
            metadata={
                "agent_work_trace_turn": turn,
                "cwd": cwd,
            },
            use_case="demo_agent_memory",
            artifact_kind="assistant_output",
            role="assistant",
            container_ref=container_ref,
            thread_ref=thread_ref,
            visibility="private",
        )


def _ingest_normal_item(
    service: PalliumService,
    *,
    source_id: str | None = None,
    thread_ref: str = THREAD_REF,
    container_ref: str = CONTAINER_REF,
    content: str = "Normal assistant response without trace metadata.",
):
    """Ingest a normal item without work trace metadata."""
    service.ingest_item(
        source_type="claude-code",
        source_id=source_id or f"cc-normal-{new_id()[:12]}",
        content_type="text/plain",
        content=content,
        metadata=None,
        use_case="demo_agent_memory",
        artifact_kind="assistant_output",
        role="assistant",
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
    )


def _get_task_traces(service: PalliumService, container_ref: str = CONTAINER_REF):
    """List active task_trace memory objects."""
    return service._storage.list_memory_objects(
        memory_types=[TASK_TRACE_TYPE],
        lifecycle="active",
        container_ref=container_ref,
    )


# ---------------------------------------------------------------------------
# TestHookExtractionE2E — hook-side extraction from transcripts
# ---------------------------------------------------------------------------


class TestHookExtractionE2E:
    """Tests for the hook-side turn extraction logic (common.py)."""

    def test_realistic_transcript_produces_valid_trace(self, tmp_path):
        """Multi-tool turn with Read, Grep, Bash, Edit produces structured trace."""
        transcript = tmp_path / "transcript.jsonl"
        turn_content = [
            {"type": "text", "text": "Let me investigate the issue."},
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "Read",
                "input": {"file_path": "/home/user/project/src/retrieval.py"},
            },
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "class RetrievalProvider:\n    def query(self): pass",
            },
            {
                "type": "tool_use",
                "id": "tool-2",
                "name": "Grep",
                "input": {"pattern": "def query", "path": "/home/user/project/src/"},
            },
            {
                "type": "tool_result",
                "tool_use_id": "tool-2",
                "content": "src/retrieval.py:5:    def query(self):\nsrc/service.py:10:    def query(self):",
            },
            {
                "type": "tool_use",
                "id": "tool-3",
                "name": "Bash",
                "input": {"command": "python -m pytest tests/ -x -q"},
            },
            {
                "type": "tool_result",
                "tool_use_id": "tool-3",
                "content": "10 passed in 2.3s\nExit code: 0",
            },
            {
                "type": "tool_use",
                "id": "tool-4",
                "name": "Edit",
                "input": {"file_path": "/home/user/project/src/retrieval.py", "old_string": "pass", "new_string": "return []"},
            },
            {
                "type": "tool_result",
                "tool_use_id": "tool-4",
                "content": "File edited successfully.",
            },
        ]

        entry = {"message": {"role": "assistant", "content": turn_content}}
        transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        turn_data = cc_common.read_turn(str(transcript))
        assert turn_data is not None
        assert turn_data.has_productive_action is True

        trace_meta = cc_common.build_work_trace_metadata(turn_data)
        assert trace_meta is not None
        assert "/home/user/project/src/retrieval.py" in trace_meta["files_read"]
        assert trace_meta["has_productive_action"] is True
        assert len(trace_meta["commands"]) == 1
        assert trace_meta["commands"][0]["exit_code"] == 0
        assert "def query" in trace_meta["grep_patterns"]

    def test_turn_with_only_reads_is_exploratory(self, tmp_path):
        """A turn with only Read tools is not productive."""
        transcript = tmp_path / "transcript.jsonl"
        turn_content = [
            {"type": "text", "text": "Let me look at the code."},
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "Read",
                "input": {"file_path": "/home/user/project/src/main.py"},
            },
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "def main(): pass",
            },
            {
                "type": "tool_use",
                "id": "tool-2",
                "name": "Read",
                "input": {"file_path": "/home/user/project/src/config.py"},
            },
            {
                "type": "tool_result",
                "tool_use_id": "tool-2",
                "content": "DEBUG = True",
            },
        ]

        entry = {"message": {"role": "assistant", "content": turn_content}}
        transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        turn_data = cc_common.read_turn(str(transcript))
        assert turn_data is not None
        assert turn_data.has_productive_action is False

        trace_meta = cc_common.build_work_trace_metadata(turn_data)
        assert trace_meta is not None
        assert trace_meta["has_productive_action"] is False
        assert "/home/user/project/src/main.py" in trace_meta["files_read"]
        assert "/home/user/project/src/config.py" in trace_meta["files_read"]
        assert trace_meta["commands"] == []

    def test_redaction_in_bash_output(self, tmp_path):
        """Secrets in bash output are redacted."""
        transcript = tmp_path / "transcript.jsonl"
        turn_content = [
            {"type": "text", "text": "Running deployment."},
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "Bash",
                "input": {"command": "deploy --token SECRET_TOKEN_123"},
            },
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "TOKEN=my-secret-value\nBearer sk-12345\nDeploy complete\nExit code: 0",
            },
        ]

        entry = {"message": {"role": "assistant", "content": turn_content}}
        transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        turn_data = cc_common.read_turn(str(transcript))
        assert turn_data is not None

        trace_meta = cc_common.build_work_trace_metadata(turn_data)
        assert trace_meta is not None
        # Secrets should be redacted in the output tail
        assert "my-secret-value" not in trace_meta["commands"][0]["output_tail"]
        assert "sk-12345" not in trace_meta["commands"][0]["output_tail"]
        assert "[REDACTED]" in trace_meta["commands"][0]["output_tail"]


# ---------------------------------------------------------------------------
# TestFullPipeline — ingest → process → query
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Full pipeline tests: ingest items with trace metadata, process, verify."""

    def test_single_session_creates_task_trace(self, service):
        """Two traced turns in a session create a single task_trace."""
        _ingest_trace_items(service, [
            {
                "files_read": ["/home/user/project/src/retrieval.py", "/home/user/project/src/config.py"],
                "commands": [],
                "grep_patterns": ["def query"],
                "has_productive_action": False,
                "files_modified": [],
            },
            {
                "files_read": ["/home/user/project/src/retrieval.py"],
                "commands": [{"cmd": "python -m pytest", "exit_code": 0, "output_tail": "5 passed", "failure_class": "success"}],
                "grep_patterns": [],
                "has_productive_action": True,
                "files_modified": ["/home/user/project/src/retrieval.py"],
            },
        ])

        service.drain_processing_queue(worker_id="e2e-test")

        traces = _get_task_traces(service)
        assert len(traces) == 1

        trace = traces[0]
        assert trace.type == TASK_TRACE_TYPE
        assert trace.schema_id == TASK_TRACE_SCHEMA_ID
        assert trace.container_ref == CONTAINER_REF
        assert trace.visibility == "private"

        payload = trace.payload
        assert payload["turn_count"] == 2
        assert "src/retrieval.py" in payload["exploratory_files"]
        assert "src/config.py" in payload["exploratory_files"]
        assert "src/retrieval.py" in payload["productive_files"]
        assert payload["first_write_action_at_turn"] == 1
        assert "python -m pytest" in payload["commands_succeeded"]
        assert payload["outcome"] == "Fixed the bug in retrieval."
        assert payload["outcome_source"] == "llm_from_agent_responses"
        assert payload["repo_ref"] == CONTAINER_REF

    def test_supersession_on_new_turn(self, test_db_url):
        """Second batch of turns triggers a rebuild that aggregates all turns.

        Since rebuild_supersedes_prior=True and each rebuild considers all thread
        items, the latest trace always includes the full session history.
        """
        storage = SQLiteStorageProvider(test_db_url)
        plugins = {
            "demo_agent_memory": DemoAgentMemoryPlugin(),
            "agent_work_trace": AgentWorkTracePlugin(provider=StubOutcomeProvider("First outcome.")),
        }
        service = PalliumService(
            storage=storage,
            retrieval=LexicalRetrievalProvider(storage),
            semantic_plugins=plugins,
            default_use_case="demo_agent_memory",
        )

        # First batch (need >= 2 items for thread rebuild to trigger)
        _ingest_trace_items(service, [
            {"files_read": ["/home/user/project/src/a.py"], "commands": [], "grep_patterns": [], "has_productive_action": False, "files_modified": []},
            {"files_read": ["/home/user/project/src/a2.py"], "commands": [], "grep_patterns": [], "has_productive_action": False, "files_modified": []},
        ])
        service.drain_processing_queue(worker_id="e2e-test")

        first_traces = _get_task_traces(service)
        assert len(first_traces) == 1
        first_payload = first_traces[0].payload
        assert first_payload["turn_count"] == 2
        assert first_payload["outcome"] == "First outcome."

        # Change outcome for second batch
        plugins["agent_work_trace"] = AgentWorkTracePlugin(provider=StubOutcomeProvider("Second outcome."))
        service._semantic_plugins = plugins

        # Second batch in same thread — adds a 3rd turn
        _ingest_trace_items(service, [
            {"files_read": ["/home/user/project/src/b.py"], "commands": [], "grep_patterns": [], "has_productive_action": True, "files_modified": ["/home/user/project/src/b.py"]},
        ])
        service.drain_processing_queue(worker_id="e2e-test")

        # The latest trace should aggregate all 3 turns
        all_traces = service._storage.list_memory_objects(
            memory_types=[TASK_TRACE_TYPE],
            container_ref=CONTAINER_REF,
        )
        active_traces = [t for t in all_traces if t.lifecycle == "active"]
        # Most recent rebuild aggregates all turns and carries "Second outcome."
        latest = max(active_traces, key=lambda t: t.created_at)
        assert latest.payload["turn_count"] == 3
        assert latest.payload["outcome"] == "Second outcome."
        assert "src/b.py" in latest.payload["productive_files"]

    def test_llm_failure_produces_task_trace_without_outcome(self, failing_service):
        """LLM failure is non-blocking; trace is created without outcome."""
        _ingest_trace_items(failing_service, [
            {
                "files_read": ["/home/user/project/src/main.py"],
                "commands": [{"cmd": "make build", "exit_code": 1, "output_tail": "Error: missing dep", "failure_class": "build_error"}],
                "grep_patterns": [],
                "has_productive_action": False,
                "files_modified": [],
            },
            {
                "files_read": ["/home/user/project/src/config.py"],
                "commands": [],
                "grep_patterns": [],
                "has_productive_action": False,
                "files_modified": [],
            },
        ])

        failing_service.drain_processing_queue(worker_id="e2e-test")

        traces = _get_task_traces(failing_service)
        assert len(traces) == 1
        payload = traces[0].payload
        assert "outcome" not in payload
        assert payload["outcome_source"] == "none"
        assert "make build" in payload["commands_failed"]

    def test_items_without_trace_metadata_do_not_produce_task_trace(self, service):
        """Normal items (no agent_work_trace_turn) don't produce task_trace."""
        _ingest_normal_item(service)
        service.drain_processing_queue(worker_id="e2e-test")

        traces = _get_task_traces(service)
        assert len(traces) == 0

    def test_lexical_retrieval_finds_task_trace(self, service):
        """Query by file path keywords returns task_trace via lexical retrieval."""
        _ingest_trace_items(service, [
            {
                "files_read": ["/home/user/project/retrieval/composite.py", "/home/user/project/retrieval/lexical.py"],
                "commands": [],
                "grep_patterns": [],
                "has_productive_action": False,
                "files_modified": [],
            },
            {
                "files_read": ["/home/user/project/retrieval/vector.py"],
                "commands": [],
                "grep_patterns": [],
                "has_productive_action": True,
                "files_modified": ["/home/user/project/retrieval/vector.py"],
            },
        ])
        service.drain_processing_queue(worker_id="e2e-test")

        # Verify the index entry was created with the expected text
        traces = _get_task_traces(service)
        assert len(traces) == 1
        payload = traces[0].payload
        assert "retrieval/composite.py" in payload["exploratory_files"]
        assert "retrieval/lexical.py" in payload["exploratory_files"]

        # Query via direct retrieval provider (bypasses query executor filters
        # that require evidence relations for container_ref matching).
        from retrieval.lexical import LexicalRetrievalProvider
        retrieval = LexicalRetrievalProvider(service._storage)
        result = retrieval.query(
            text="retrieval composite lexical",
            limit=10,
            visibility="private",
            query_container_ref=CONTAINER_REF,
        )

        # Should find the task trace
        task_trace_hits = [r for r in result.results if r.type == TASK_TRACE_TYPE]
        assert len(task_trace_hits) >= 1, (
            f"Expected task_trace in retrieval results, got types: {[r.type for r in result.results]}"
        )


# ---------------------------------------------------------------------------
# TestEdgeCases — path normalization and caps
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for path normalization and caps."""

    def test_windows_paths_normalized(self):
        """Windows backslash paths are normalized relative to cwd."""
        result = normalize_path(
            "C:\\Users\\dev\\project\\src\\main.py",
            "C:\\Users\\dev\\project",
        )
        assert result == "src/main.py"

    def test_relative_dot_path_normalized(self):
        """./prefixed paths are cleaned."""
        result = normalize_path("./src/main.py", None)
        assert result == "src/main.py"

    def test_already_relative_path_unchanged(self):
        """Already-relative paths pass through."""
        result = normalize_path("src/main.py", None)
        assert result == "src/main.py"

    def test_empty_files_list_produces_empty_subject(self):
        """Empty file list produces empty subject string."""
        result = _compute_subject([])
        assert result == ""

    def test_single_file_produces_dir_subject(self):
        """Single file in a directory produces 'dir/' subject."""
        result = _compute_subject(["src/main.py"])
        assert result == "src/"

    def test_root_file_produces_filename_subject(self):
        """File at root (no dir) produces filename as subject."""
        result = _compute_subject(["README.md"])
        assert result == "README.md"

    def test_caps_enforced_on_large_sessions(self, test_db_url):
        """100 files are capped at MAX_EXPLORATORY_FILES."""
        storage = SQLiteStorageProvider(test_db_url)
        plugins = {
            "demo_agent_memory": DemoAgentMemoryPlugin(),
            "agent_work_trace": AgentWorkTracePlugin(provider=StubOutcomeProvider()),
        }
        svc = PalliumService(
            storage=storage,
            retrieval=LexicalRetrievalProvider(storage),
            semantic_plugins=plugins,
            default_use_case="demo_agent_memory",
        )

        many_files = [f"/home/user/project/src/file_{i}.py" for i in range(100)]
        _ingest_trace_items(svc, [
            {"files_read": many_files[:50], "commands": [], "grep_patterns": [], "has_productive_action": False, "files_modified": []},
            {"files_read": many_files[50:], "commands": [], "grep_patterns": [], "has_productive_action": False, "files_modified": []},
        ])
        svc.drain_processing_queue(worker_id="e2e-test")

        traces = _get_task_traces(svc)
        assert len(traces) == 1
        payload = traces[0].payload
        assert len(payload["exploratory_files"]) == MAX_EXPLORATORY_FILES



# ---------------------------------------------------------------------------
# TestRegressions — ensure normal paths are not broken
# ---------------------------------------------------------------------------


class TestRegressions:
    """Regression tests: normal ingest still works, mixed items, parallel coexistence."""

    def test_normal_ingest_still_works(self, service):
        """Items without trace metadata are processed normally — no task_trace produced."""
        _ingest_normal_item(
            service,
            content="Decision: We will use event-time ordering for reservation queue processing.",
        )
        service.drain_processing_queue(worker_id="e2e-test")

        # No task_trace should be created
        traces = _get_task_traces(service)
        assert len(traces) == 0

        # The item should be processed successfully (status = completed)
        from storage.sqlite_schema import SourceItemRecord
        from sqlalchemy import select
        with service._storage._session_factory() as session:
            items = session.scalars(select(SourceItemRecord)).all()
            assert len(items) == 1
            assert items[0].processing_status == "completed"

    def test_mixed_items_in_same_thread(self, service):
        """One traced item and one normal item in the same thread.

        The traced items should produce a task_trace;
        the normal item should not interfere.
        """
        # Ingest a normal item first
        _ingest_normal_item(service, content="I can help with that.")

        # Ingest traced items in the same thread (need >= 2 for thread rebuild)
        _ingest_trace_items(service, [
            {
                "files_read": ["/home/user/project/src/service.py"],
                "commands": [{"cmd": "python -m pytest", "exit_code": 0, "output_tail": "3 passed", "failure_class": "success"}],
                "grep_patterns": [],
                "has_productive_action": False,
                "files_modified": [],
            },
            {
                "files_read": ["/home/user/project/src/service.py"],
                "commands": [],
                "grep_patterns": [],
                "has_productive_action": True,
                "files_modified": ["/home/user/project/src/service.py"],
            },
        ])

        service.drain_processing_queue(worker_id="e2e-test")

        traces = _get_task_traces(service)
        assert len(traces) == 1
        assert traces[0].payload["turn_count"] == 2
        assert "src/service.py" in traces[0].payload["productive_files"]

    def test_parallel_processing_does_not_conflict_with_primary_package(self, service):
        """Item with trace metadata is processed by both demo_agent_memory and agent_work_trace.

        Both packages should process without error, and agent_work_trace produces task_trace.
        """
        _ingest_trace_items(service, [
            {
                "files_read": ["/home/user/project/src/main.py"],
                "commands": [],
                "grep_patterns": [],
                "has_productive_action": False,
                "files_modified": [],
            },
            {
                "files_read": ["/home/user/project/src/utils.py"],
                "commands": [],
                "grep_patterns": [],
                "has_productive_action": True,
                "files_modified": ["/home/user/project/src/utils.py"],
            },
        ])

        service.drain_processing_queue(worker_id="e2e-test")

        # agent_work_trace should produce task_trace
        traces = _get_task_traces(service)
        assert len(traces) == 1

        # Items should be fully processed (completed status)
        from storage.sqlite_schema import SourceItemRecord
        from sqlalchemy import select
        with service._storage._session_factory() as session:
            items = session.scalars(select(SourceItemRecord)).all()
            for item in items:
                assert item.processing_status == "completed"
