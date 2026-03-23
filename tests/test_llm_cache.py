"""Tests for the file-backed LLM response cache."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from providers.llm.base import LLMJsonResponse, LLMProvider
from providers.llm.cached import CachedLLMProvider


def _mock_provider() -> MagicMock:
    mock = MagicMock(spec=LLMProvider)
    mock.generate_json.return_value = LLMJsonResponse(
        raw_text='{"result": "test"}',
        parsed_json={"result": "test"},
        metadata=None,
    )
    return mock


class TestCachedLLMProvider:
    def test_miss_then_hit(self, tmp_path: Path) -> None:
        mock = _mock_provider()
        cached = CachedLLMProvider(mock, cache_dir=tmp_path)

        # First call — cache miss, delegates to mock.
        r1 = cached.generate_json(
            system_prompt="sys", user_prompt="user", schema_description="schema",
        )
        assert r1.parsed_json == {"result": "test"}
        assert mock.generate_json.call_count == 1

        # Second call — cache hit, does NOT delegate.
        r2 = cached.generate_json(
            system_prompt="sys", user_prompt="user", schema_description="schema",
        )
        assert r2.parsed_json == {"result": "test"}
        assert mock.generate_json.call_count == 1  # Still 1 — cached.

    def test_different_prompts_separate_entries(self, tmp_path: Path) -> None:
        mock = _mock_provider()
        cached = CachedLLMProvider(mock, cache_dir=tmp_path)

        cached.generate_json(system_prompt="a", user_prompt="b", schema_description="c")
        cached.generate_json(system_prompt="x", user_prompt="y", schema_description="z")
        assert mock.generate_json.call_count == 2

    def test_stats_tracked(self, tmp_path: Path) -> None:
        mock = _mock_provider()
        cached = CachedLLMProvider(mock, cache_dir=tmp_path)

        cached.generate_json(system_prompt="s", user_prompt="u", schema_description="d")
        cached.generate_json(system_prompt="s", user_prompt="u", schema_description="d")
        cached.generate_json(system_prompt="s2", user_prompt="u2", schema_description="d2")

        assert cached.stats == {"hits": 1, "misses": 2}

    def test_cache_persists_across_instances(self, tmp_path: Path) -> None:
        mock1 = _mock_provider()
        cached1 = CachedLLMProvider(mock1, cache_dir=tmp_path)
        cached1.generate_json(system_prompt="s", user_prompt="u", schema_description="d")

        # New instance, same cache dir.
        mock2 = _mock_provider()
        cached2 = CachedLLMProvider(mock2, cache_dir=tmp_path)
        r = cached2.generate_json(system_prompt="s", user_prompt="u", schema_description="d")

        assert r.parsed_json == {"result": "test"}
        assert mock2.generate_json.call_count == 0  # Never called — served from cache.
