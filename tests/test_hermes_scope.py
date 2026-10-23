"""Standalone Hermes identity parity and filesystem trust-boundary checks."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from core.work_ref import readable_work_ref


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scope = load("hermes_scope_test", "integrations/hermes/scope.py")
common = load("hermes_scope_reference", "integrations/codex/hooks/common.py")
# Compare identity rules independently of the legacy Windows locale decoder.
common.subprocess = SimpleNamespace(**vars(subprocess))
common.subprocess.run = lambda *a, **kw: subprocess.run(*a, **{"encoding": "utf-8", **kw})


def git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


def private_git_home(tmp_path, monkeypatch, name=""):
    home = tmp_path / "private-git-home"
    home.mkdir()
    config = home / ".gitconfig"
    config.write_text(f"[user]\n name = {name}\n" if name else "", encoding="utf-8")
    for key in tuple(os.environ):
        if key.upper().startswith("GIT_"):
            monkeypatch.delenv(key)
    for key, value in {"HOME": str(home), "USERPROFILE": str(home),
                       "XDG_CONFIG_HOME": str(home / "xdg"),
                       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(config)}.items():
        monkeypatch.setenv(key, value)
    native_run = subprocess.run

    def run(*args, **kwargs):
        return native_run(*args, **{**kwargs, "env": {**(kwargs.get("env") or os.environ),
                            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(config)}})

    isolated = SimpleNamespace(**vars(subprocess))
    isolated.run = run
    monkeypatch.setattr(scope, "subprocess", isolated)
    reference = SimpleNamespace(**vars(subprocess))
    reference.run = lambda *args, **kwargs: run(*args, **{"encoding": "utf-8", **kwargs})
    monkeypatch.setattr(common, "subprocess", reference)
    monkeypatch.setattr(sys.modules[__name__], "git", lambda cwd, *args: run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        encoding="utf-8").stdout.strip())
    return config


def repo(path, remote=None, branch="feat/scope-שלום"):
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Scope שלום")
    git(path, "config", "user.email", "scope@example.test")
    git(path, "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "initial")
    if remote:
        git(path, "remote", "add", "origin", remote)
    git(path, "checkout", "-b", branch)
    return path


@pytest.mark.parametrize("remote", [None, "git@github.com:TEAM/Scope.git",
    "https://github.com/team/scope.git", "ssh://git@example.test:2222/Team/Scope.git"])
def test_git_container_actor_and_work_refs_match_existing(tmp_path, remote):
    project = repo(tmp_path / "פרויקט", remote)
    tasks = project / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "scope-שלום.md").write_text(
        "<!-- agent-workflow:start -->\nvalid\n<!-- agent-workflow:end -->", encoding="utf-8")
    resolved = scope.resolve_scope(str(project))
    assert resolved["container_ref"] == common.derive_container_ref(str(project))
    assert resolved["actor_ref"] == common.derive_actor_ref(str(project)) == "Scope שלום"
    expected = common.structural_work_refs_payload(resolved["container_ref"],
        common.discover_work_refs(str(project)), str(project))
    assert resolved["work_refs"] == expected
    assert len(expected) == 2
    for row in expected:
        assert readable_work_ref(**row).key.startswith("work:v1:")


def test_worktree_same_origin_and_actor_config_change(tmp_path):
    first = repo(tmp_path / "first", "https://github.com/team/scope.git")
    second = tmp_path / "second"
    git(first, "worktree", "add", "-b", "fix/second", str(second))
    a = scope.resolve_scope(str(first))
    b = scope.resolve_scope(str(second), a)
    assert a["container_ref"] == b["container_ref"]
    assert b["work_refs"][0]["local_ref"] == "git-branch:fix/second"
    git(first, "config", "user.name", "Changed שלום")
    assert scope.resolve_scope(str(second), b)["actor_ref"] == "Changed שלום"


def test_project_transition_and_transient_non_git_pin(tmp_path, monkeypatch):
    private_git_home(tmp_path, monkeypatch)
    first = repo(tmp_path / "first", "https://github.com/team/first.git")
    second = repo(tmp_path / "second", "https://github.com/team/second.git")
    git(second, "config", "user.name", "Second")
    transient = tmp_path / "temporary"
    transient.mkdir()
    a = scope.resolve_scope(str(first))
    pinned = scope.resolve_scope(str(transient), a)
    assert pinned == {**a, "cwd": str(transient), "actor_ref": "local", "work_refs": []}
    b = scope.resolve_scope(str(second), pinned)
    assert b["container_ref"] != a["container_ref"]
    assert b["actor_ref"] == "Second"
    monkeypatch.setenv("PALLIUM_HOOK_ACTOR_REF", "Environment")
    assert scope.resolve_scope(str(second), b)["actor_ref"] == "Environment"
    assert scope.resolve_scope(str(second), b, "Profile")["actor_ref"] == "Profile"


def test_transient_actor_follows_reference_caller_under_private_git_home(tmp_path, monkeypatch):
    private_config = private_git_home(tmp_path, monkeypatch, "Global Bob")
    monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF", raising=False)
    cache = tmp_path / "codex-session-cache"
    cache.mkdir()
    monkeypatch.setattr(common, "SESSIONS_DIR", cache)
    first = repo(tmp_path / "first", "https://example.test/team/first.git")
    git(first, "config", "user.name", "Alice")
    second = repo(tmp_path / "second", "https://example.test/team/second.git")
    git(second, "config", "user.name", "Carol")
    transient = tmp_path / "temporary"
    transient.mkdir()
    sid = "private-parity-session"
    previous = None
    for index, (cwd, actor) in enumerate(((first, "Alice"), (transient, "Global Bob"),
                                          (second, "Carol"), (first, "Alice"))):
        expected_container = common.resolve_container_ref(str(cwd), sid, True, False)
        expected_actor = common.derive_actor_ref(str(cwd), sid, expected_container)
        actual = scope.resolve_scope(str(cwd), previous)
        assert actual["container_ref"] == expected_container
        assert actual["actor_ref"] == expected_actor == actor
        if index in (0, 2, 3):
            assert common.pin_container(sid, actual["container_ref"])
        previous = actual
    private_config.write_text("", encoding="utf-8")
    expected_container = common.resolve_container_ref(str(transient), sid, True, False)
    expected_actor = common.derive_actor_ref(str(transient), sid, expected_container)
    local = scope.resolve_scope(str(transient), previous)
    assert local["container_ref"] == expected_container == previous["container_ref"]
    assert local["actor_ref"] == expected_actor == "local"
    monkeypatch.setenv("PALLIUM_HOOK_ACTOR_REF", "Environment")
    assert scope.resolve_scope(str(transient), previous)["actor_ref"] == "Environment"
    assert scope.resolve_scope(str(transient), previous, "Profile")["actor_ref"] == "Profile"
    assert scope.resolve_scope(str(transient), previous, "   ")["actor_ref"] == "Environment"
    monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF")
    assert scope.resolve_scope(str(transient), previous, "   ")["actor_ref"] == "local"
    monkeypatch.setenv("PALLIUM_HOOK_ACTOR_REF", "unsafe\nactor")
    with pytest.raises(ValueError, match="actor identity"):
        scope.resolve_scope(str(transient), previous)


def test_non_git_path_matches_reference_and_local_actor(tmp_path, monkeypatch):
    monkeypatch.setattr(scope, "_git", lambda *_: None)
    resolved = scope.resolve_scope(str(tmp_path))
    assert resolved["container_ref"] == common._path_container(str(tmp_path))
    assert resolved["actor_ref"] == "local"
    assert resolved["work_refs"] == []


@pytest.mark.parametrize("cwd", [None, "", ".", "relative/path", 12,
    "//server/share", "\\\\server\\share", "https://example.test/repo", "\0"])
def test_invalid_cwd_never_defaults_to_process_cwd(cwd, monkeypatch):
    monkeypatch.setattr(scope.subprocess, "run", lambda *_a, **_k: pytest.fail("Git called"))
    with pytest.raises(ValueError):
        scope.resolve_scope(cwd, {"container_ref": "git:previous/project"})


def test_missing_file_and_remote_drive_cwd_rejected(tmp_path, monkeypatch):
    file = tmp_path / "file"
    file.write_text("not a directory")
    for path in (tmp_path / "missing", file):
        with pytest.raises(ValueError):
            scope.resolve_scope(str(path))
    monkeypatch.setattr(scope, "_windows_drive_is_local", lambda _: False)
    with pytest.raises(ValueError):
        scope.resolve_scope(str(tmp_path))


def test_inherited_git_repository_and_config_overrides_are_removed(tmp_path, monkeypatch):
    first = repo(tmp_path / "first", "https://github.com/team/first.git")
    second = repo(tmp_path / "second", "https://github.com/team/second.git")
    expected = scope.resolve_scope(str(first))
    monkeypatch.setenv("GIT_DIR", str(second / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(second))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "Spoofed")
    assert scope.resolve_scope(str(first)) == expected


@pytest.mark.parametrize("remote", ["https://example.test/team/repo?token=private",
    "https://user:password@example.test/team/repo.git", "file:///tmp/repo",
    "https://example.test/team/ghp_" + "A" * 40,
    "https://example.test/team/repo?api_key=private"])
def test_unsafe_origin_is_refused_without_identity_fallback(tmp_path, remote):
    project = repo(tmp_path / "repo", remote)
    assert scope.canonical_git_remote(remote) is None
    assert common.canonical_git_remote(remote) is None
    with pytest.raises(ValueError, match="safe supported Git remote"):
        scope.resolve_scope(str(project), {"container_ref": "git:previous/project"})


@pytest.mark.parametrize("remote", ["https://GitHub.com/Team/Scope.git",
    "ssh://git@example.test:22/Team/Scope.git", "git@example.test:Team/Scope.git",
    "https://example.test:443/Team/Scope.git", "https://example.test/Team/Cafe%CC%81.git",
    "https://example.test/team/../repo", "https://example.test:/team/repo",
    "https://example.test/team/repo?secret=private", "https://example.test/%XX"])
def test_remote_canonicalization_matches_reference(remote):
    assert scope.canonical_git_remote(remote) == common.canonical_git_remote(remote)


@pytest.mark.parametrize("branch", ["main", "master", "develop", "trunk"])
def test_default_branch_has_no_work_refs(tmp_path, branch):
    project = repo(tmp_path / "repo", branch="feat/temp")
    git(project, "checkout", "-B", branch)
    assert scope.resolve_scope(str(project))["work_refs"] == []


@pytest.mark.parametrize("record", ["", "<!-- agent-workflow:start -->", 
    "<!-- agent-workflow:end --><!-- agent-workflow:start -->", "x" * (256 * 1024 + 1)],
    ids=["empty", "missing-end", "reversed", "oversize"])
def test_invalid_or_oversize_work_record_keeps_only_branch(tmp_path, record):
    project = repo(tmp_path / "repo", branch="feat/example")
    tasks = project / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "example.md").write_text(record)
    (tasks / "unrelated.md").write_text("<!-- agent-workflow:start --><!-- agent-workflow:end -->")
    resolved = scope.resolve_scope(str(project))
    assert [r["local_ref"] for r in resolved["work_refs"]] == ["git-branch:feat/example"]


def test_detached_head_has_no_work_refs(tmp_path):
    project = repo(tmp_path / "repo")
    git(project, "checkout", "--detach")
    assert scope.resolve_scope(str(project))["work_refs"] == []


def test_head_change_during_discovery_discards_work_refs(tmp_path, monkeypatch):
    project = repo(tmp_path / "repo")
    original = scope._bounded_text
    reads = 0
    def changed_head(path, limit):
        nonlocal reads
        text = original(path, limit)
        if path.name == "HEAD":
            reads += 1
            if reads == 2:
                return "ref: refs/heads/fix/changed\n"
        return text
    monkeypatch.setattr(scope, "_bounded_text", changed_head)
    assert scope.resolve_scope(str(project))["work_refs"] == []


def test_reparse_work_record_is_never_read(tmp_path, monkeypatch):
    project = repo(tmp_path / "repo", branch="feat/example")
    tasks = project / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    record = tasks / "example.md"
    record.write_text("<!-- agent-workflow:start --><!-- agent-workflow:end -->")
    original = scope._safe_lstat
    def reject_reparse(path):
        if path == record:
            raise OSError("unsafe reparse point")
        return original(path)
    monkeypatch.setattr(scope, "_safe_lstat", reject_reparse)
    assert [r["local_ref"] for r in scope.resolve_scope(str(project))["work_refs"]] == ["git-branch:feat/example"]


def test_git_is_read_only_and_bounded(tmp_path, monkeypatch):
    calls = []
    def timeout(*args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(scope.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="timed out"):
        scope.resolve_scope(str(tmp_path))
    env = calls[0][1]["env"]
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert env["GIT_NO_LAZY_FETCH"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert 0 < calls[0][1]["timeout"] <= 1
