"""File-backed LLM response cache for eval and benchmark runs.

Wraps any LLMProvider and caches generate_json responses keyed on
(system_prompt, user_prompt, schema_description, model_tag). Cache entries
are stored as individual JSON files in a cache directory.

Usage:
    provider = build_llm_provider(config, provider_name=..., model=...)
    cached = CachedLLMProvider(provider, cache_dir=Path(".local/llm-cache"), model_tag="sonnet")
    # Use cached instead of provider — same interface, cached responses.

Note: cached responses have metadata=None (provider name, attempt count, etc.
are not preserved). This is acceptable for eval tooling.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from providers.llm.base import LLMJsonResponse, LLMProvider

logger = logging.getLogger(__name__)


class CachedLLMProvider(LLMProvider):
    """LLM provider wrapper that caches generate_json responses to disk.

    Thread-safe: each cache entry is a separate file, writes use unique
    tmp names to prevent collision, and counters are lock-protected.
    """

    def __init__(self, delegate: LLMProvider, cache_dir: Path, model_tag: str | None = None) -> None:
        self._delegate = delegate
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # Derive model_tag from delegate if not explicitly provided.
        self._model_tag = model_tag or getattr(delegate, "_model", "unknown")
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_description: str,
    ) -> LLMJsonResponse:
        cache_key = _cache_key(system_prompt, user_prompt, schema_description, self._model_tag)
        cache_path = self._cache_dir / f"{cache_key}.json"

        # Cache hit.
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                with self._lock:
                    self._hits += 1
                return LLMJsonResponse(
                    raw_text=data["raw_text"],
                    parsed_json=data["parsed_json"],
                    metadata=None,
                )
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupted cache entry %s, regenerating", cache_key)

        # Cache miss — call the real provider.
        response = self._delegate.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=schema_description,
        )
        with self._lock:
            self._misses += 1

        # Write cache entry with a unique tmp name to prevent collision
        # when multiple threads miss the same key simultaneously.
        tmp_path = self._cache_dir / f"{cache_key}_{uuid.uuid4().hex[:8]}.tmp"
        try:
            tmp_path.write_text(
                json.dumps({
                    "raw_text": response.raw_text,
                    "parsed_json": response.parsed_json,
                }, default=str),
                encoding="utf-8",
            )
            # os.replace is atomic on both POSIX and Windows.
            import os
            os.replace(str(tmp_path), str(cache_path))
        except OSError:
            # Non-fatal: cache write failed, next call will retry.
            tmp_path.unlink(missing_ok=True)

        return response

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"hits": self._hits, "misses": self._misses}


def _cache_key(system_prompt: str, user_prompt: str, schema_description: str, model_tag: str) -> str:
    """Compute a stable cache key from the prompt inputs and model."""
    h = hashlib.sha256()
    h.update(model_tag.encode("utf-8"))
    h.update(b"\x00")
    h.update(system_prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(user_prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(schema_description.encode("utf-8"))
    return h.hexdigest()[:24]
