"""Tests for the Codex Stop hook's ``_fetch_memory_match_text``.

Same Phase 5b contract as the Claude Code Stop hook (the Codex hook
shares the matcher module with Claude Code). See:

  - tests/test_claude_code_hooks/test_stop_match_text.py
  - docs/specs/2026-06-27-injection-policy-abstention.md Phase 5b
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock


def _import_codex_stop():
    """Import integrations/codex/hooks/stop.py as a standalone module.

    The Codex hook uses ``importlib.util.spec_from_file_location`` to load
    its own siblings, so we load it the same way here to avoid colliding
    with the Claude Code hook on ``sys.path``.
    """
    stop_path = (
        Path(__file__).resolve().parent.parent
        / "integrations"
        / "codex"
        / "hooks"
        / "stop.py"
    )
    spec = importlib.util.spec_from_file_location("codex_stop_under_test", str(stop_path))
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["codex_stop_under_test"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class TestCodexFetchMemoryMatchText:
    def test_prefers_server_match_text_when_present(self) -> None:
        stop = _import_codex_stop()
        server_payload = {
            "memory_object_id": "abc",
            "match_text": "Question: where did we leave off. Answer: at Phase 6.",
            "payload": {"summary": "should not be used"},
            "items": [],
        }
        with mock.patch.object(stop, "pallium_request", return_value=server_payload):
            text = stop._fetch_memory_match_text("abc")
        assert text == "Question: where did we leave off. Answer: at Phase 6."

    def test_falls_back_to_scalar_fields_when_no_match_text(self) -> None:
        stop = _import_codex_stop()
        server_payload = {
            "memory_object_id": "abc",
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
        stop = _import_codex_stop()
        server_payload = {
            "memory_object_id": "abc",
            "match_text": None,
            "payload": {"summary": "fallback summary"},
            "items": [],
        }
        with mock.patch.object(stop, "pallium_request", return_value=server_payload):
            text = stop._fetch_memory_match_text("abc")
        assert "fallback summary" in text

    def test_returns_empty_on_no_response(self) -> None:
        stop = _import_codex_stop()
        with mock.patch.object(stop, "pallium_request", return_value=None):
            text = stop._fetch_memory_match_text("abc")
        assert text == ""

    def test_returns_empty_on_empty_memory_object_id(self) -> None:
        stop = _import_codex_stop()
        with mock.patch.object(stop, "pallium_request") as m:
            text = stop._fetch_memory_match_text("")
        assert text == ""
        assert not m.called
