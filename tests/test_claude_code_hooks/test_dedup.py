"""Tests for dedup checking logic."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"))

import common


class TestCheckDedup:
    def setup_method(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._orig_state_dir = common.STATE_DIR
        common.STATE_DIR = Path(self._tmp_dir)

    def teardown_method(self):
        common.STATE_DIR = self._orig_state_dir
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_first_occurrence_not_duplicate(self):
        assert common.check_dedup("hello world prompt", "session-1") is False

    def test_repeat_within_window_is_duplicate(self):
        common.check_dedup("hello world prompt", "session-1")
        assert common.check_dedup("hello world prompt", "session-1") is True

    def test_different_prompt_not_duplicate(self):
        common.check_dedup("prompt one", "session-1")
        assert common.check_dedup("prompt two", "session-1") is False

    def test_different_session_independent(self):
        common.check_dedup("same prompt", "session-a")
        assert common.check_dedup("same prompt", "session-b") is False

    def test_expired_entry_not_duplicate(self):
        common.check_dedup("hello", "s1")
        state_file = common.STATE_DIR / "s1.json"
        state = json.loads(state_file.read_text())
        for key in state:
            state[key] = time.time() - 400
        state_file.write_text(json.dumps(state))

        assert common.check_dedup("hello", "s1") is False

    def test_corrupted_state_file_handled(self):
        state_file = common.STATE_DIR / "s1.json"
        state_file.write_text("not valid json {{{{")
        assert common.check_dedup("test prompt", "s1") is False

    def test_missing_state_dir_created(self):
        common.STATE_DIR = Path(self._tmp_dir) / "subdir" / "nested"
        assert common.check_dedup("test", "s1") is False
        assert common.STATE_DIR.exists()

    def test_state_file_written(self):
        common.check_dedup("my prompt", "sess")
        state_file = common.STATE_DIR / "sess.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert len(state) == 1
