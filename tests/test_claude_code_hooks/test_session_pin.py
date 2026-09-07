"""Tests for SessionStart-based container pinning.

The pin system is intended to keep a single Claude session's memories in
one container even when Claude Code's tracked cwd drifts mid-session
(e.g. agent runs `cd subdir`).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"))

import common  # noqa: E402


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """Redirect STATE_DIR + SESSIONS_DIR to a tmp path for isolation."""
    monkeypatch.setattr(common, "STATE_DIR", tmp_path)
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path / "sessions")
    return tmp_path


# --- pin_container / get_pinned_container roundtrip ---


class TestPinAndGet:
    def test_roundtrip(self, tmp_state):
        common.pin_container("session-abc", "git:github.com/foo/bar")
        assert common.get_pinned_container("session-abc") == "git:github.com/foo/bar"

    def test_get_missing_returns_none(self, tmp_state):
        assert common.get_pinned_container("never-pinned") is None

    def test_get_with_no_session_id_returns_none(self, tmp_state):
        assert common.get_pinned_container(None) is None
        assert common.get_pinned_container("") is None

    def test_pin_creates_sessions_dir(self, tmp_state):
        assert not (tmp_state / "sessions").exists()
        common.pin_container("session-x", "path:abc:123")
        assert (tmp_state / "sessions").exists()

    def test_pinned_value_persists_across_calls(self, tmp_state):
        common.pin_container("s1", "container-a")
        # Simulate process restart by calling fresh
        assert common.get_pinned_container("s1") == "container-a"


# --- Validation / safety ---


class TestPinValidation:
    @pytest.mark.parametrize("bad_id", [
        None, "", "..", "../etc/passwd", "a/b", "a\\b", "a b", "a:b",
        "a;b", "a\nb", "a.b", "name with spaces",
    ])
    def test_rejects_unsafe_session_id(self, tmp_state, bad_id):
        common.pin_container(bad_id, "container-x")
        # No file should be created
        sessions = tmp_state / "sessions"
        if sessions.exists():
            assert list(sessions.iterdir()) == []
        assert common.get_pinned_container(bad_id) is None

    @pytest.mark.parametrize("good_id", [
        "abc123", "a-b-c", "a_b_c", "ABC", "0123456789",
        "uuid-style-49c1ce36-1c25-4e18-adaa-2a5ee00a3ca1",
    ])
    def test_accepts_safe_session_id(self, tmp_state, good_id):
        common.pin_container(good_id, "container-x")
        assert common.get_pinned_container(good_id) == "container-x"

    def test_empty_container_ref_no_op(self, tmp_state):
        common.pin_container("session-1", "")
        assert common.get_pinned_container("session-1") is None

    def test_non_string_container_ref_no_op(self, tmp_state):
        common.pin_container("session-1", None)  # type: ignore[arg-type]
        common.pin_container("session-1", 42)  # type: ignore[arg-type]
        assert common.get_pinned_container("session-1") is None


# --- Corrupted / partial state on disk ---


class TestCorruptedState:
    def test_corrupted_json_returns_none(self, tmp_state):
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "broken.json").write_text("{not valid json", encoding="utf-8")
        assert common.get_pinned_container("broken") is None

    def test_non_dict_payload_returns_none(self, tmp_state):
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "list-payload.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert common.get_pinned_container("list-payload") is None

    def test_missing_field_returns_none(self, tmp_state):
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "no-ref.json").write_text(json.dumps({"ts": 1234}), encoding="utf-8")
        assert common.get_pinned_container("no-ref") is None

    def test_empty_string_field_returns_none(self, tmp_state):
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "blank.json").write_text(json.dumps({"container_ref": ""}), encoding="utf-8")
        assert common.get_pinned_container("blank") is None

    def test_recovers_after_corruption(self, tmp_state):
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "rec.json").write_text("garbage", encoding="utf-8")
        # New SessionStart overwrites with valid pin
        common.pin_container("rec", "good-container")
        assert common.get_pinned_container("rec") == "good-container"


# --- Resume / clear stickiness ---


class TestResumeStickiness:
    def test_fresh_start_writes_pin(self, tmp_state):
        common.pin_container("s1", "container-fresh", source="startup")
        assert common.get_pinned_container("s1") == "container-fresh"

    def test_resume_preserves_existing_pin(self, tmp_state):
        common.pin_container("s1", "original-container", source="startup")
        common.pin_container("s1", "new-container", source="resume")
        assert common.get_pinned_container("s1") == "original-container"

    def test_clear_preserves_existing_pin(self, tmp_state):
        common.pin_container("s1", "original-container", source="startup")
        common.pin_container("s1", "new-container", source="clear")
        assert common.get_pinned_container("s1") == "original-container"

    def test_resume_writes_pin_when_absent(self, tmp_state):
        # Edge: SessionStart fired with source=resume but no prior pin
        # (e.g. first session after this code shipped). Should create pin.
        common.pin_container("s1", "container-x", source="resume")
        assert common.get_pinned_container("s1") == "container-x"

    def test_clear_writes_pin_when_absent(self, tmp_state):
        common.pin_container("s1", "container-x", source="clear")
        assert common.get_pinned_container("s1") == "container-x"

    def test_fresh_start_overwrites_existing(self, tmp_state):
        # If a session_id is somehow reused with source=startup, overwrite.
        common.pin_container("s1", "old-container", source="startup")
        common.pin_container("s1", "new-container", source="startup")
        assert common.get_pinned_container("s1") == "new-container"

    def test_no_source_overwrites_existing(self, tmp_state):
        common.pin_container("s1", "old-container")
        common.pin_container("s1", "new-container")
        assert common.get_pinned_container("s1") == "new-container"


# --- resolve_container_ref ---


class TestResolveContainerRef:
    @patch("common.subprocess.run")
    def test_pinned_wins_over_cwd(self, mock_run, tmp_state):
        # Even if cwd would derive to a git container, the pin is honored.
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "https://github.com/elsewhere/repo.git\n"
        common.pin_container("s1", "git:pinned/value")
        result = common.resolve_container_ref("/some/cwd", "s1")
        assert result == "git:pinned/value"

    @patch("common.subprocess.run")
    def test_falls_back_to_derive_when_no_pin(self, mock_run, tmp_state):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "https://github.com/cwd/repo.git\n"
        result = common.resolve_container_ref("/some/cwd", "unpinned")
        assert result == "git:github.com/cwd/repo"

    @patch("common.subprocess.run")
    def test_falls_back_when_session_id_none(self, mock_run, tmp_state):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "https://github.com/cwd/repo.git\n"
        result = common.resolve_container_ref("/some/cwd", None)
        assert result == "git:github.com/cwd/repo"

    @patch("common.subprocess.run")
    def test_falls_back_when_session_id_invalid(self, mock_run, tmp_state):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "https://github.com/cwd/repo.git\n"
        result = common.resolve_container_ref("/some/cwd", "../bad")
        assert result == "git:github.com/cwd/repo"

    @patch("common.subprocess.run")
    def test_pin_survives_cwd_drift(self, mock_run, tmp_state):
        """Regression: the bug we observed in thread 49c1ce36 — same session
        produces memories in different containers as cwd drifts. Pinning
        must keep all turns in the original container.
        """
        # SessionStart at xlm root: not a git repo
        mock_run.return_value.returncode = 128
        mock_run.return_value.stdout = ""
        from common import derive_container_ref, pin_container, resolve_container_ref
        original = derive_container_ref("/work/xlm")
        pin_container("s1", original, source="startup")
        # Mid-session: agent cd'd into pelican (which IS a git repo)
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "git@github.tools.sap:xlm/pelican.git\n"
        # Subsequent hooks must still see the original pin
        result = resolve_container_ref("/work/xlm/pelican", "s1")
        assert result == original
        assert result.startswith("path:")  # not git: of pelican

    @patch("common.subprocess.run")
    def test_deliberate_git_project_switch_updates_pin(
        self, mock_run, tmp_state, tmp_path, monkeypatch,
    ):
        root, _git_dir = _fake_repo(tmp_path, monkeypatch)
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "https://github.com/new/repo.git\n"
        common.pin_container("s1", "git:old/repo")
        result = common.resolve_container_ref(
            str(root), "s1", allow_project_switch=True,
        )
        assert result == "git:github.com/new/repo"
        assert common.get_pinned_container("s1") == result
        assert common.get_pending_relay_closes("s1") == ["git:old/repo"]
        common.pin_container("s1", result, pending_relay_closes=[])
        assert common.get_pending_relay_closes("s1") == []

    @patch("common.subprocess.run")
    def test_transient_non_git_cwd_does_not_replace_git_pin(self, mock_run, tmp_state):
        mock_run.return_value.returncode = 128
        mock_run.return_value.stdout = ""
        common.pin_container("s1", "git:old/repo")
        result = common.resolve_container_ref("/tmp", "s1", allow_project_switch=True)
        assert result == "git:old/repo"
        assert common.get_pinned_container("s1") == "git:old/repo"


# --- Atomic write ---


class TestAtomicWrite:
    def test_no_partial_file_left_at_canonical_path(self, tmp_state):
        """If the write succeeds, the canonical path always contains valid JSON."""
        common.pin_container("s1", "container-a")
        fp = tmp_state / "sessions" / "s1.json"
        assert fp.exists()
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["container_ref"] == "container-a"

    def test_tmp_file_cleaned_up_on_success(self, tmp_state):
        common.pin_container("s1", "container-a")
        sessions = tmp_state / "sessions"
        tmp_files = list(sessions.glob("*.tmp"))
        assert tmp_files == []

    def test_tmp_file_cleaned_up_on_replace_failure(self, tmp_state, monkeypatch):
        """If os.replace fails after write, tmp file should be cleaned up."""
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)

        original_replace = common.os.replace
        call_count = {"n": 0}
        def failing_replace(src, dst):
            call_count["n"] += 1
            raise OSError("simulated rename failure")
        monkeypatch.setattr(common.os, "replace", failing_replace)

        common.pin_container("s1", "container-a")

        # Canonical file shouldn't exist; tmp shouldn't be left behind
        assert not (sessions / "s1.json").exists()
        assert not (sessions / "s1.json.tmp").exists()
        assert call_count["n"] == 1

        # Restore
        monkeypatch.setattr(common.os, "replace", original_replace)


# --- Sweep ---


class TestSweep:
    def test_old_files_removed(self, tmp_state):
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        old_file = sessions / "old.json"
        old_file.write_text(json.dumps({"container_ref": "x"}), encoding="utf-8")
        # Set mtime to 31 days ago
        ancient = time.time() - 31 * 24 * 3600
        import os
        os.utime(old_file, (ancient, ancient))

        common._sweep_old_session_pins()

        assert not old_file.exists()

    def test_recent_files_kept(self, tmp_state):
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        recent = sessions / "recent.json"
        recent.write_text(json.dumps({"container_ref": "x"}), encoding="utf-8")

        common._sweep_old_session_pins()

        assert recent.exists()

    def test_sweep_when_dir_missing(self, tmp_state):
        # Should not crash
        common._sweep_old_session_pins()

    def test_pin_call_triggers_sweep(self, tmp_state):
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        old_file = sessions / "old.json"
        old_file.write_text(json.dumps({"container_ref": "x"}), encoding="utf-8")
        ancient = time.time() - 31 * 24 * 3600
        import os
        os.utime(old_file, (ancient, ancient))

        # Pin a different session — sweep should run as side effect
        common.pin_container("new-session", "container-new")

        assert not old_file.exists()
        assert (sessions / "new-session.json").exists()


# --- Stable identity cache ---


def _fake_repo(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text("[remote \"origin\"]\nurl = example\n", encoding="utf-8")
    monkeypatch.setattr(common, "_find_repo", lambda _cwd: (root, git_dir))
    return root, git_dir


class TestIdentityCache:
    def test_same_repo_reuses_container_and_actor_without_git(self, tmp_state, tmp_path, monkeypatch):
        root, _git_dir = _fake_repo(tmp_path, monkeypatch)
        calls = []

        def run(command, **_kwargs):
            calls.append(tuple(command))
            return common.subprocess.CompletedProcess(command, 0, "משתמש\n", "")

        monkeypatch.setattr(common.subprocess, "run", run)
        common.pin_container("s1", "git:example/repo", source="startup")

        assert common.derive_actor_ref(str(root), "s1") == "משתמש"
        assert common.resolve_container_ref(str(root), "s1", True) == "git:example/repo"
        assert common.derive_actor_ref(str(root), "s1") == "משתמש"
        assert calls == [("git", "config", "user.name")]

    def test_repo_config_change_refreshes_container_and_actor(self, tmp_state, tmp_path, monkeypatch):
        root, git_dir = _fake_repo(tmp_path, monkeypatch)
        calls = []

        def run(command, **_kwargs):
            calls.append(tuple(command))
            output = "https://example.test/repo.git\n" if command[1] == "remote" else f"Actor-{len(calls)}\n"
            return common.subprocess.CompletedProcess(command, 0, output, "")

        monkeypatch.setattr(common.subprocess, "run", run)
        common.pin_container("s1", "git:example.test/repo", source="startup")
        assert common.derive_actor_ref(str(root), "s1") == "Actor-1"

        (git_dir / "config").write_text("[user]\nname = changed\n", encoding="utf-8")
        assert common.resolve_container_ref(str(root), "s1", True) == "git:example.test/repo"
        assert common.derive_actor_ref(str(root), "s1") == "Actor-3"
        assert calls == [
            ("git", "config", "user.name"),
            ("git", "remote", "get-url", "origin"),
            ("git", "config", "user.name"),
        ]

    def test_work_refs_remain_live_while_identity_is_cached(self, tmp_state, tmp_path, monkeypatch):
        root, git_dir = _fake_repo(tmp_path, monkeypatch)
        tasks = root / ".agent-workflow" / "tasks"
        tasks.mkdir(parents=True)
        for slug in ("one", "two"):
            (tasks / f"{slug}.md").write_text(
                "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
                encoding="utf-8",
            )
        (git_dir / "HEAD").write_text("ref: refs/heads/feature/one\n", encoding="utf-8")
        monkeypatch.setattr(
            common.subprocess,
            "run",
            lambda command, **_kwargs: common.subprocess.CompletedProcess(command, 0, "Actor\n", ""),
        )
        common.pin_container("s1", "git:example/repo", source="startup")
        common.derive_actor_ref(str(root), "s1")

        assert "git-branch:feature/one" in common.discover_work_refs(str(root)).structural_refs
        (git_dir / "HEAD").write_text("ref: refs/heads/feature/two\n", encoding="utf-8")
        assert "git-branch:feature/two" in common.discover_work_refs(str(root)).structural_refs

    def test_lock_failure_returns_fresh_actor(self, tmp_state, tmp_path, monkeypatch):
        root, _git_dir = _fake_repo(tmp_path, monkeypatch)
        monkeypatch.setattr(common, "_acquire_session_lock", lambda _session_id: None)
        monkeypatch.setattr(
            common.subprocess,
            "run",
            lambda command, **_kwargs: common.subprocess.CompletedProcess(
                command, 0, "Fresh Actor\n", ""
            ),
        )

        assert common.derive_actor_ref(str(root), "s1") == "Fresh Actor"
        assert common.get_pinned_container("s1") is None
    def test_corrupt_state_recomputes_instead_of_using_stale_scope(self, tmp_state, tmp_path, monkeypatch):
        root, _git_dir = _fake_repo(tmp_path, monkeypatch)
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "s1.json").write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(
            common.subprocess,
            "run",
            lambda command, **_kwargs: common.subprocess.CompletedProcess(
                command, 0, "https://example.test/fresh.git\n", ""
            ),
        )

        assert common.resolve_container_ref(str(root), "s1", True) == "git:example.test/fresh"

    def test_interleaved_updates_preserve_unknown_and_pending_fields(self, tmp_state, tmp_path, monkeypatch):
        root, _git_dir = _fake_repo(tmp_path, monkeypatch)
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "s1.json").write_text(
            json.dumps({
                "container_ref": "git:example/repo",
                "pending_relay_closes": ["git:example/old"],
                "legacy": {"keep": True},
            }),
            encoding="utf-8",
        )
        context = common._identity_context(str(root))
        assert common._cache_identity_context("s1", context, actor_ref="Actor")
        common.pin_container(
            "s1",
            "git:example/repo",
            pending_relay_closes=["git:example/old"],
        )

        state = json.loads((sessions / "s1.json").read_text(encoding="utf-8"))
        assert state["legacy"] == {"keep": True}
        assert state["pending_relay_closes"] == ["git:example/old"]
        assert state["actor_ref"] == "Actor"
        assert list(sessions.glob("*.tmp")) == []


class TestIdentityCacheTransitions:
    def test_resume_refreshes_old_live_state_before_sweep(self, tmp_state):
        common.pin_container(
            "s1",
            "git:example/repo",
            pending_relay_closes=["git:example/old"],
        )
        state_file = tmp_state / "sessions" / "s1.json"
        ancient = time.time() - common.SESSION_PIN_TTL_SECONDS - 60
        import os
        os.utime(state_file, (ancient, ancient))

        assert common.pin_container(
            "s1",
            "git:ignored/repo",
            source="resume",
        )
        assert common.get_pinned_container("s1") == "git:example/repo"
        assert common.get_pending_relay_closes("s1") == ["git:example/old"]
        assert state_file.stat().st_mtime > ancient

    def test_overlapping_project_switch_unions_predecessor_under_lock(self, tmp_state):
        assert common.pin_container("s1", "git:example/one", source="startup")
        stale_pending = common.get_pending_relay_closes("s1")

        assert common.pin_container("s1", "git:example/two")
        assert common.pin_container(
            "s1",
            "git:example/three",
            pending_relay_closes=stale_pending,
        )

        assert common.get_pinned_container("s1") == "git:example/three"
        assert common.get_pending_relay_closes("s1") == [
            "git:example/one",
            "git:example/two",
        ]

    def test_stale_close_completion_cannot_erase_newer_transition(self, tmp_state):
        assert common.pin_container("s1", "git:example/one", source="startup")
        assert common.pin_container(
            "s1",
            "git:example/two",
            pending_relay_closes=["git:example/one"],
        )
        pending, stale_generation = common.get_pending_relay_close_batch("s1")
        assert pending == ["git:example/one"]

        assert common.pin_container(
            "s1",
            "git:example/three",
            pending_relay_closes=["git:example/one", "git:example/two"],
        )
        assert common.complete_relay_closes(
            "s1",
            ["git:example/one"],
            stale_generation,
        )
        assert common.get_pinned_container("s1") == "git:example/three"
        assert common.get_pending_relay_closes("s1") == [
            "git:example/one",
            "git:example/two",
        ]

        pending, current_generation = common.get_pending_relay_close_batch("s1")
        assert common.complete_relay_closes(
            "s1",
            [pending[0]],
            current_generation,
        )
        assert common.get_pending_relay_closes("s1") == ["git:example/two"]

    def test_project_switch_lock_failure_keeps_existing_scope(
        self, tmp_state, monkeypatch,
    ):
        common.pin_container("s1", "git:example/old", source="startup")
        monkeypatch.setattr(common, "_identity_context", lambda _cwd: None)
        monkeypatch.setattr(common, "_acquire_session_lock", lambda _session_id: None)
        monkeypatch.setattr(
            common,
            "derive_container_ref",
            lambda _cwd: "git:example/new",
        )

        assert common.resolve_container_ref("/new/repo", "s1", True) == "git:example/old"
        assert common.get_pinned_container("s1") == "git:example/old"
        assert common.get_pending_relay_closes("s1") == []

    def test_legacy_actor_without_identity_context_is_recomputed(
        self, tmp_state, tmp_path, monkeypatch,
    ):
        root, _git_dir = _fake_repo(tmp_path, monkeypatch)
        sessions = tmp_state / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "s1.json").write_text(
            json.dumps({
                "container_ref": "git:example/repo",
                "actor_ref": "stale",
            }),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            common.subprocess,
            "run",
            lambda command, **_kwargs: common.subprocess.CompletedProcess(
                command, 0, "Fresh\n", ""
            ),
        )

        assert common.derive_actor_ref(str(root), "s1") == "Fresh"

# --- Codex parity ---


def test_codex_helpers_mirror_claude_code(tmp_path, monkeypatch):
    """Codex hooks must expose the same pin API."""
    import importlib.util
    codex_path = Path(__file__).resolve().parent.parent.parent / "integrations" / "codex" / "hooks" / "common.py"
    spec = importlib.util.spec_from_file_location("codex_common_test", codex_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["codex_common_test"] = mod  # required for @dataclass to resolve
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        monkeypatch.setattr(mod, "STATE_DIR", tmp_path)
        monkeypatch.setattr(mod, "SESSIONS_DIR", tmp_path / "sessions")

        mod.pin_container("s-codex", "git:foo/bar")
        assert mod.get_pinned_container("s-codex") == "git:foo/bar"
        assert mod.resolve_container_ref("/whatever", "s-codex") == "git:foo/bar"

        mod.pin_container("s-codex", "git:something-else", source="resume")
        assert mod.get_pinned_container("s-codex") == "git:foo/bar"  # sticky
    finally:
        sys.modules.pop("codex_common_test", None)
