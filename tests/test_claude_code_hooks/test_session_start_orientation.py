"""Tests for the SessionStart orientation-query grounding (Fix A).

The orientation query is built from structural git signals (branch name +
changed/recent file stems) instead of a fixed generic phrase, so its
candidates carry real lexical overlap and clear the retrieval grounding
gates on merit. These tests pin the query-derivation logic and the
graceful fallback, driving through the hook module the same way the other
hook tests do.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

# Hooks import path (mirrors the other hook tests).
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"),
)


def _import_session_start():
    import importlib
    import common
    import session_start as ss

    importlib.reload(common)
    importlib.reload(ss)
    return ss


class TestDeriveOrientationQuery:
    def test_branch_and_changed_files_produce_grounded_query(self):
        ss = _import_session_start()

        def fake_git(cwd, *args, strip=True):
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return "fix-injection-triggers-orientation"
            if args[0] == "status":
                # Realistic porcelain: worktree-only change → column X is a
                # space (" M path"); a root-level file must survive parsing.
                return " M config.py\n?? notes.txt\n"
            if args[0] == "log":
                return "semantic/agent_conversation_memory_routing_selection.py\napp/settings.py\n"
            return ""

        with mock.patch.object(ss, "_git", side_effect=fake_git):
            query = ss._derive_orientation_query("/repo")

        # Branch tokens split on separators.
        assert "injection" in query and "orientation" in query
        # Root-level worktree file stem must survive porcelain parsing (regression:
        # a global strip would corrupt " M config.py" → "onfig").
        assert "config" in query
        assert "onfig" not in query.split()
        # Committed-file stem also present.
        assert "settings" in query
        # Not the generic fallback.
        assert query != ss.RETRIEVAL_FALLBACK_QUERY

    def test_root_level_worktree_file_not_corrupted(self):
        """Regression for the _git().strip() first-line porcelain bug.

        A worktree-only modification to a repo-root file has a leading-space
        porcelain prefix (" M Makefile"); the path offset must be preserved.
        """
        ss = _import_session_start()

        def fake_git(cwd, *args, strip=True):
            if args[0] == "status":
                return " M Makefile\n M README.md\n"
            return ""

        with mock.patch.object(ss, "_git", side_effect=fake_git):
            stems = ss._changed_file_tokens("/repo")
        assert "Makefile" in stems
        assert "README" in stems
        # No corrupted first-line token.
        assert "akefile" not in stems

    def test_generic_branch_clean_tree_falls_back(self):
        ss = _import_session_start()

        def fake_git(cwd, *args, strip=True):
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return "main"
            return ""  # clean tree, no recent files

        with mock.patch.object(ss, "_git", side_effect=fake_git):
            query = ss._derive_orientation_query("/repo")

        assert query == ss.RETRIEVAL_FALLBACK_QUERY

    def test_no_git_falls_back(self):
        ss = _import_session_start()
        with mock.patch.object(ss, "_git", return_value=""):
            query = ss._derive_orientation_query("/not-a-repo")
        assert query == ss.RETRIEVAL_FALLBACK_QUERY

    def test_changed_files_capped(self):
        ss = _import_session_start()
        many = "\n".join(f" M dir/file{i}.py" for i in range(30))

        def fake_git(cwd, *args, strip=True):
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return "main"  # generic → rely on file signal only
            if args[0] == "status":
                return many
            return ""

        with mock.patch.object(ss, "_git", side_effect=fake_git):
            stems = ss._changed_file_tokens("/repo")
        assert len(stems) <= ss._MAX_CHANGED_FILES

    def test_rename_arrow_uses_new_path(self):
        ss = _import_session_start()

        def fake_git(cwd, *args, strip=True):
            if args[0] == "status":
                return "R  old_name.py -> new_name.py"
            return ""

        with mock.patch.object(ss, "_git", side_effect=fake_git):
            stems = ss._changed_file_tokens("/repo")
        assert "new_name" in stems
        assert "old_name" not in stems


class TestOrientationQueryTaggedTrigger:
    def test_fetch_uses_orientation_trigger_origin(self):
        ss = _import_session_start()
        sent = []

        def fake_request(method, path, payload):
            sent.append((method, path, payload))
            return {"injectable_blocks": []}

        with mock.patch.object(ss, "pallium_request", side_effect=fake_request):
            ss._fetch_orientation("branch tokens here", "git:repo", "user")

        assert len(sent) == 1
        _, path, payload = sent[0]
        assert path == "/query"
        assert payload["trigger_origin"] == "session_start_orientation"
        assert payload["text"] == "branch tokens here"
        assert payload["container_ref"] == "git:repo"
