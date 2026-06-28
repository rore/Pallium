"""Tests for the claude-code Stop hook's ``_fetch_memory_match_text``.

Phase 5b (2026-06-28): the hook should prefer the server-side
``match_text`` field from the ``/memory/{id}/expand`` response and only
fall back to the legacy scalar-field coalesce for older Pallium servers
that predate that field.

See:
  - docs/specs/2026-06-27-injection-policy-abstention.md Phase 5b
  - tests/test_phase5b_match_text.py (server-side plumbing tests)
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import mock

# Hooks import path
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"),
)


def _import_stop():
    import common
    import usage_audit_matcher
    import stop

    importlib.reload(common)
    importlib.reload(usage_audit_matcher)
    importlib.reload(stop)
    return stop


class TestFetchMemoryMatchText:
    def test_prefers_server_match_text_when_present(self) -> None:
        stop = _import_stop()
        # Server returns match_text — the hook must use it verbatim and
        # NOT fall back to the scalar-field coalesce.
        server_payload = {
            "memory_object_id": "abc",
            "match_text": "Task: refactor routing. Next step: split resolver.",
            "payload": {
                # These would normally be ignored by the scalar coalesce
                # (no `summary`, no `decision`, etc.), but the test asserts
                # the hook takes match_text without ever looking at payload.
                "task": "different task",
                "summary": "should not be used",
            },
            "items": [],
        }
        with mock.patch.object(stop, "pallium_request", return_value=server_payload):
            text = stop._fetch_memory_match_text("abc")
        assert text == "Task: refactor routing. Next step: split resolver."

    def test_falls_back_to_scalar_fields_when_no_match_text(self) -> None:
        stop = _import_stop()
        # Older server: response omits match_text. The hook must derive
        # text from the legacy hardcoded scalar list so the populator keeps
        # working without a server upgrade.
        server_payload = {
            "memory_object_id": "abc",
            # match_text key absent entirely
            "payload": {
                "summary": "Investigation summary line",
                "investigation_outcome": "Root cause: clock skew",
            },
            "items": [],
        }
        with mock.patch.object(stop, "pallium_request", return_value=server_payload):
            text = stop._fetch_memory_match_text("abc")
        assert "Investigation summary line" in text
        assert "Root cause: clock skew" in text

    def test_falls_back_when_match_text_is_null(self) -> None:
        """Server sends match_text=None for unembeddable memory types
        (e.g. task_trace). The hook must still try the scalar fallback."""
        stop = _import_stop()
        server_payload = {
            "memory_object_id": "abc",
            "match_text": None,
            "payload": {
                "summary": "fallback summary",
            },
            "items": [],
        }
        with mock.patch.object(stop, "pallium_request", return_value=server_payload):
            text = stop._fetch_memory_match_text("abc")
        assert "fallback summary" in text

    def test_falls_back_when_match_text_is_empty_string(self) -> None:
        stop = _import_stop()
        server_payload = {
            "memory_object_id": "abc",
            "match_text": "",
            "payload": {
                "summary": "fallback summary",
            },
            "items": [],
        }
        with mock.patch.object(stop, "pallium_request", return_value=server_payload):
            text = stop._fetch_memory_match_text("abc")
        assert "fallback summary" in text

    def test_returns_empty_on_no_response(self) -> None:
        stop = _import_stop()
        with mock.patch.object(stop, "pallium_request", return_value=None):
            text = stop._fetch_memory_match_text("abc")
        assert text == ""

    def test_returns_empty_on_empty_memory_object_id(self) -> None:
        stop = _import_stop()
        # Should short-circuit before calling pallium_request at all.
        with mock.patch.object(stop, "pallium_request") as m:
            text = stop._fetch_memory_match_text("")
        assert text == ""
        assert not m.called
