"""Tests for MCP environment-based context resolution."""

from __future__ import annotations

import pytest

from app.mcp.context import resolve_context, PalliumContext


class TestResolveContext:
    """resolve_context merges explicit params with env var defaults."""

    def test_all_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        monkeypatch.setenv("PALLIUM_CONTAINER_REF", "slack:channel:C04ABC")
        monkeypatch.setenv("PALLIUM_THREAD_REF", "slack:thread:C04ABC:123")
        monkeypatch.setenv("PALLIUM_ACTOR_REF", "slack:user:U789")
        monkeypatch.setenv("PALLIUM_VISIBILITY", "container")

        ctx = resolve_context()
        assert ctx.base_url == "http://localhost:8000"
        assert ctx.container_ref == "slack:channel:C04ABC"
        assert ctx.thread_ref == "slack:thread:C04ABC:123"
        assert ctx.actor_ref == "slack:user:U789"
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
        monkeypatch.delenv("PALLIUM_VISIBILITY", raising=False)

        ctx = resolve_context()
        assert ctx.base_url == "http://localhost:8000"
        assert ctx.container_ref is None
        assert ctx.thread_ref is None
        assert ctx.actor_ref is None
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
