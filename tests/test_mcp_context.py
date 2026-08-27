"""Tests for MCP environment-based context resolution."""

from __future__ import annotations

import pytest

from app.mcp.context import PalliumContext, _canonicalize_container_ref, resolve_context


class TestResolveContext:
    """resolve_context merges explicit params with env var defaults."""

    def test_all_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        monkeypatch.setenv("PALLIUM_CONTAINER_REF", "slack:channel:C04ABC")
        monkeypatch.setenv("PALLIUM_THREAD_REF", "slack:thread:C04ABC:123")
        monkeypatch.setenv("PALLIUM_ACTOR_REF", "slack:user:U789")
        monkeypatch.setenv("PALLIUM_AGENT_REF", "claude-code")
        monkeypatch.setenv("PALLIUM_VISIBILITY", "container")

        ctx = resolve_context()
        assert ctx.base_url == "http://localhost:8000"
        assert ctx.container_ref == "slack:channel:C04ABC"
        assert ctx.thread_ref == "slack:thread:C04ABC:123"
        assert ctx.actor_ref == "slack:user:U789"
        assert ctx.agent_ref == "claude-code"
        assert ctx.visibility == "container"

    def test_explicit_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_CONTAINER_REF", "env-container")
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")

        ctx = resolve_context(container_ref="explicit-container")
        assert ctx.container_ref == "explicit-container"

    def test_explicit_none_falls_through_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_CONTAINER_REF", "env-container")
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")

        ctx = resolve_context(container_ref=None)
        assert ctx.container_ref == "env-container"

    def test_missing_env_returns_none_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        monkeypatch.delenv("PALLIUM_CONTAINER_REF", raising=False)
        monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
        monkeypatch.delenv("PALLIUM_ACTOR_REF", raising=False)
        monkeypatch.delenv("PALLIUM_AGENT_REF", raising=False)
        monkeypatch.delenv("PALLIUM_VISIBILITY", raising=False)

        ctx = resolve_context()
        assert ctx.base_url == "http://localhost:8000"
        assert ctx.container_ref is None
        assert ctx.thread_ref is None
        assert ctx.actor_ref is None
        assert ctx.agent_ref is None
        assert ctx.visibility is None

    def test_missing_base_url_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PALLIUM_BASE_URL", raising=False)

        ctx = resolve_context()
        assert ctx.base_url is None


class TestPalliumContext:
    """PalliumContext.is_configured checks base_url presence."""

    def test_configured_when_base_url_set(self) -> None:
        ctx = PalliumContext(base_url="http://localhost:8000")
        assert ctx.is_configured is True

    def test_not_configured_when_base_url_none(self) -> None:
        ctx = PalliumContext(base_url=None)
        assert ctx.is_configured is False
@pytest.mark.parametrize(
    "value",
    [
        "git:github.com/Owner/Repo",
        "GIT:GITHUB.COM/Owner/Repo/",
        "Git:GitHub.Com/Owner/Repo.git",
        "git:github.com/Owner/Repo.git/",
    ],
)
def test_github_container_forms_canonicalize(value: str) -> None:
    assert _canonicalize_container_ref(value) == "git:github.com/owner/repo"


def test_github_container_canonicalization_is_idempotent() -> None:
    canonical = "git:github.com/owner/repo"
    assert _canonicalize_container_ref(_canonicalize_container_ref(canonical)) == canonical


def test_github_container_canonicalization_applies_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("PALLIUM_CONTAINER_REF", "GIT:GITHUB.COM/Owner/Repo.GIT/")
    assert resolve_context().container_ref == "git:github.com/owner/repo"


@pytest.mark.parametrize(
    "value",
    [
        "git:gitlab.com/Owner/Repo.git",
        "GitHub:Owner/Repo.git",
        "git:github.com/Owner/Repo/extra",
        "slack:Channel:CaseSensitive",
    ],
)
def test_unknown_container_refs_are_preserved(value: str) -> None:
    assert _canonicalize_container_ref(value) == value


def test_codex_thread_ref_comes_from_runtime_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "codex-session-123")
    assert resolve_context().thread_ref == "codex-session-123"


def test_explicit_thread_ref_overrides_runtime_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("PALLIUM_THREAD_REF", "pallium-session")
    monkeypatch.setenv("CODEX_THREAD_ID", "codex-session")
    assert resolve_context().thread_ref == "pallium-session"


def test_claude_thread_ref_comes_from_parent_session_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import json
    import app.mcp.context as context

    registry = tmp_path / ".claude" / "sessions"
    registry.mkdir(parents=True)
    (registry / "123.json").write_text(
        json.dumps({"pid": 123, "sessionId": "claude-session-456"}), encoding="utf-8"
    )
    monkeypatch.setenv("PALLIUM_AGENT_REF", "claude-code")
    monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(context.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(context.os, "getppid", lambda: 123)
    assert resolve_context().thread_ref == "claude-session-456"


def test_claude_registry_pid_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import json
    import app.mcp.context as context

    registry = tmp_path / ".claude" / "sessions"
    registry.mkdir(parents=True)
    (registry / "123.json").write_text(
        json.dumps({"pid": 999, "sessionId": "wrong-session"}), encoding="utf-8"
    )
    monkeypatch.setenv("PALLIUM_AGENT_REF", "claude-code")
    monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(context.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(context.os, "getppid", lambda: 123)
    assert resolve_context().thread_ref is None