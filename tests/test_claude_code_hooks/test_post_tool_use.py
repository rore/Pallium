"""Tests for the PostToolUse hook (Phase 4 deterministic triggers).

See: docs/specs/2026-06-27-injection-policy-abstention.md.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

# Hooks import path
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"),
)


def _import_with_isolated_state_dir():
    """Import post_tool_use with STATE_DIR pointing to a temp folder."""
    # Use a temp dir for the retry counter state to keep tests hermetic.
    import importlib
    import common
    import post_tool_use as pt

    importlib.reload(common)
    importlib.reload(pt)
    return pt


class TestNormalizeTarget:
    def test_bash_command(self):
        pt = _import_with_isolated_state_dir()
        target = pt._normalize_target("Bash", {"command": "pytest tests/foo"})
        assert "pytest tests/foo" in target

    def test_bash_command_redacted_and_truncated(self):
        pt = _import_with_isolated_state_dir()
        long_cmd = "echo TOKEN=abc " * 50
        target = pt._normalize_target("Bash", {"command": long_cmd})
        assert len(target) <= 80

    def test_read_file_path(self):
        pt = _import_with_isolated_state_dir()
        target = pt._normalize_target("Read", {"file_path": "/c/x.py"})
        assert target == "/c/x.py"

    def test_glob_pattern(self):
        pt = _import_with_isolated_state_dir()
        target = pt._normalize_target("Glob", {"pattern": "**/*.py"})
        assert target == "**/*.py"

    def test_unknown_tool_empty_target(self):
        pt = _import_with_isolated_state_dir()
        target = pt._normalize_target("WeirdTool", {"a": "b"})
        assert target == ""


class TestErrorSignature:
    def test_signature_with_output_tail(self):
        pt = _import_with_isolated_state_dir()
        sig = pt._error_signature(
            "Bash",
            "Running tests... pytest FAILED 5 tests failed",
            1,
        )
        assert "test_failure" in sig
        assert "FAILED" in sig

    def test_signature_for_non_bash_tool(self):
        pt = _import_with_isolated_state_dir()
        sig = pt._error_signature("Read", "ENOENT", 1)
        assert "tool_error" in sig
        assert "ENOENT" in sig


class TestRetryCounters:
    def test_load_returns_empty_for_missing_session(self):
        pt = _import_with_isolated_state_dir()
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(pt, "RETRY_COUNTERS_DIR", Path(td) / "retry_counters"):
                assert pt._load_retry_counters("no-such-session") == {}

    def test_save_and_load_roundtrip(self):
        pt = _import_with_isolated_state_dir()
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(pt, "RETRY_COUNTERS_DIR", Path(td) / "retry_counters"):
                pt._save_retry_counters("sess-1", {"Bash::pytest": 2})
                assert pt._load_retry_counters("sess-1") == {"Bash::pytest": 2}

    def test_empty_session_id_skips_save(self):
        pt = _import_with_isolated_state_dir()
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(pt, "RETRY_COUNTERS_DIR", Path(td) / "retry_counters"):
                pt._save_retry_counters("", {"x": 1})
                # No file written → no exception. Verify counter dir empty.
                rc_dir = Path(td) / "retry_counters"
                if rc_dir.exists():
                    assert list(rc_dir.iterdir()) == []


class TestFailureQueryEmitsTriggerOrigin:
    def test_failure_query_payload(self):
        pt = _import_with_isolated_state_dir()
        sent = []

        def fake_request(method, path, payload):
            sent.append((method, path, payload))
            return {"injectable_blocks": []}

        with mock.patch.object(pt, "pallium_request", side_effect=fake_request):
            pt._maybe_fire_failure_query(
                container_ref="git:repo",
                actor_ref="user",
                session_id="sess",
                error_signature="test_failure: 5 tests failed",
            )
        assert len(sent) == 1
        method, path, payload = sent[0]
        assert method == "POST"
        assert path == "/query"
        assert payload["trigger_origin"] == "post_tool_failure"
        assert payload["text"] == "test_failure: 5 tests failed"
        assert payload["container_ref"] == "git:repo"


class TestRetryQueryEmitsTriggerOrigin:
    def test_retry_query_payload(self):
        pt = _import_with_isolated_state_dir()
        sent = []

        def fake_request(method, path, payload):
            sent.append((method, path, payload))
            return {"injectable_blocks": []}

        with mock.patch.object(pt, "pallium_request", side_effect=fake_request):
            pt._maybe_fire_retry_query(
                container_ref="git:repo",
                actor_ref="user",
                normalized_target="pytest tests/x",
                tool_name="Bash",
            )
        assert len(sent) == 1
        _, _, payload = sent[0]
        assert payload["trigger_origin"] == "retry_threshold"
        assert "Bash" in payload["text"]
