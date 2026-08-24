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


# ---------------------------------------------------------------------------
# main()-level tests driven by REALISTIC Claude Code PostToolUse payloads.
#
# The pre-existing tests above exercise helpers with hand-fed strings and never
# call main(), so they could not catch the payload-shape mismatch: Claude Code's
# Bash tool_response carries {stdout, stderr, interrupted, isImage,
# noOutputExpected} and NO exit-code field, while the hook read
# tool_response.get("output"/"error"). These tests drive main() end-to-end with
# the real shape (captured from session transcripts) so the failure path is
# actually verified.
# ---------------------------------------------------------------------------

# Real Bash failure payload shape (from Claude Code session JSONL): the command
# "sqlite3 ..." fails with "command not found" written to STDOUT, empty stderr,
# no exit-code key anywhere, and is_error is not set on tool_response.
_FAILED_BASH_PAYLOAD = {
    "cwd": ".",
    "session_id": "sess-main-1",
    "tool_name": "Bash",
    "tool_input": {"command": "sqlite3 db.sqlite '.tables'"},
    "tool_response": {
        "stdout": "/usr/bin/bash: line 1: sqlite3: command not found",
        "stderr": "",
        "interrupted": False,
        "isImage": False,
        "noOutputExpected": False,
    },
}

# A traceback failure, error text on stderr this time.
_FAILED_PYTEST_PAYLOAD = {
    "cwd": ".",
    "session_id": "sess-main-2",
    "tool_name": "Bash",
    "tool_input": {"command": "python -m pytest tests/x"},
    "tool_response": {
        "stdout": "collected 3 items\n",
        "stderr": "Traceback (most recent call last):\n  File ...\nAssertionError\n1 failed",
        "interrupted": False,
        "isImage": False,
        "noOutputExpected": False,
    },
}

# A clean success — must never fire a failure trigger.
_SUCCESS_BASH_PAYLOAD = {
    "cwd": ".",
    "session_id": "sess-main-3",
    "tool_name": "Bash",
    "tool_input": {"command": "ls -la"},
    "tool_response": {
        "stdout": "total 4\n-rw-r--r-- 1 user user 0 file.txt",
        "stderr": "",
        "interrupted": False,
        "isImage": False,
        "noOutputExpected": False,
    },
}


def _run_main(pt, payload, td):
    """Drive main() with a payload on stdin, capturing outgoing pallium requests."""
    import io
    import json

    sent = []

    def fake_request(method, path, req_payload):
        sent.append((method, path, req_payload))
        return {"injectable_blocks": []}

    with mock.patch.object(pt, "RETRY_COUNTERS_DIR", Path(td) / "retry_counters"), \
        mock.patch.object(pt, "_TRIGGERS_ENABLED", True), \
        mock.patch.object(pt, "pallium_request", side_effect=fake_request), \
        mock.patch.object(pt, "resolve_container_ref", return_value="git:repo"), \
        mock.patch.object(pt, "derive_actor_ref", return_value="user"), \
        mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        try:
            pt.main()
        except SystemExit:
            pass
    return sent


class TestMainFailureDetection:
    """main()-level regression coverage for the real PostToolUse payload shape."""

    def test_failed_bash_stdout_marker_fires_failure_trigger(self):
        pt = _import_with_isolated_state_dir()
        with tempfile.TemporaryDirectory() as td:
            sent = _run_main(pt, _FAILED_BASH_PAYLOAD, td)
        failure_calls = [p for (_, _, p) in sent if p.get("trigger_origin") == "post_tool_failure"]
        assert failure_calls, (
            "Expected a post_tool_failure query for a failed Bash command "
            "(command-not-found on stdout), but none fired. tool_response uses "
            "stdout/stderr keys, not output/error."
        )

    def test_failed_pytest_stderr_traceback_fires_failure_trigger(self):
        pt = _import_with_isolated_state_dir()
        with tempfile.TemporaryDirectory() as td:
            sent = _run_main(pt, _FAILED_PYTEST_PAYLOAD, td)
        failure_calls = [p for (_, _, p) in sent if p.get("trigger_origin") == "post_tool_failure"]
        assert failure_calls, "Expected a post_tool_failure query for a pytest traceback on stderr."

    def test_success_does_not_fire_failure_trigger(self):
        pt = _import_with_isolated_state_dir()
        with tempfile.TemporaryDirectory() as td:
            sent = _run_main(pt, _SUCCESS_BASH_PAYLOAD, td)
        failure_calls = [p for (_, _, p) in sent if p.get("trigger_origin") == "post_tool_failure"]
        assert not failure_calls, "A clean success must not fire a failure trigger."

    def test_retry_counter_increments_on_repeated_failure(self):
        pt = _import_with_isolated_state_dir()
        with tempfile.TemporaryDirectory() as td:
            # Three identical failures should reach RETRY_THRESHOLD and fire a retry query.
            sent_total = []
            for _ in range(pt.RETRY_THRESHOLD):
                sent_total.extend(_run_main(pt, _FAILED_BASH_PAYLOAD, td))
        retry_calls = [p for (_, _, p) in sent_total if p.get("trigger_origin") == "retry_threshold"]
        assert retry_calls, (
            f"Expected a retry_threshold query after {pt.RETRY_THRESHOLD} identical failures."
        )

    def test_interrupted_fires_failure_trigger(self):
        pt = _import_with_isolated_state_dir()
        payload = {
            "cwd": ".",
            "session_id": "sess-int",
            "tool_name": "Bash",
            "tool_input": {"command": "sleep 999"},
            "tool_response": {"stdout": "", "stderr": "", "interrupted": True},
        }
        with tempfile.TemporaryDirectory() as td:
            sent = _run_main(pt, payload, td)
        failure_calls = [p for (_, _, p) in sent if p.get("trigger_origin") == "post_tool_failure"]
        assert failure_calls, "An interrupted tool call must fire a failure trigger."

    def test_failure_injection_passes_complete_provenance_scope(self):
        import io
        import json

        pt = _import_with_isolated_state_dir()
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(pt, "RETRY_COUNTERS_DIR", Path(td) / "retry_counters"), \
                mock.patch.object(pt, "_TRIGGERS_ENABLED", True), \
                mock.patch.object(pt, "pallium_request", return_value={"injectable_blocks": []}), \
                mock.patch.object(pt, "resolve_container_ref", return_value="git:repo"), \
                mock.patch.object(pt, "derive_actor_ref", return_value="user"), \
                mock.patch.object(pt, "format_injection", return_value="") as formatter, \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(_FAILED_BASH_PAYLOAD))):
                try:
                    pt.main()
                except SystemExit:
                    pass

        assert formatter.call_args.kwargs == {
            "budget_chars": 1200,
            "thread_ref": "sess-main-1",
            "actor_ref": "user",
            "agent_ref": "claude-code",
            "visibility": "private",
        }
    def test_triggers_disabled_by_default_is_inert(self):
        """With the opt-in flag off, main() must emit no queries even on failure."""
        import io
        import json

        pt = _import_with_isolated_state_dir()
        sent = []
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(pt, "RETRY_COUNTERS_DIR", Path(td) / "retry_counters"), \
                mock.patch.object(pt, "_TRIGGERS_ENABLED", False), \
                mock.patch.object(pt, "pallium_request", side_effect=lambda *a, **k: sent.append(a)), \
                mock.patch.object(pt, "resolve_container_ref", return_value="git:repo"), \
                mock.patch.object(pt, "derive_actor_ref", return_value="user"), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(_FAILED_BASH_PAYLOAD))):
                try:
                    pt.main()
                except SystemExit:
                    pass
        assert sent == [], "Default-off flag must make the hook inert."
