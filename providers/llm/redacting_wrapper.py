"""Redacting wrapper for :class:`providers.llm.base.LLMProvider`.

Introduced 2026-07-02 as PR 0 step 7 — the retrieval barrier's
defense-in-depth against LLM extractors that copy secrets from
source into their structured output.

Even though :func:`core.service.PalliumService.ingest_item` now
redacts ``source_items.content`` at the write barrier (PR 0 step 6),
an LLM re-materializing a secret in ``parsed_json`` (e.g., the
model paraphrases a redacted marker and hallucinates back a
credential-shaped token) could still land unredacted values into
``MemoryObject.payload``. This wrapper closes that gap by
redacting every string leaf of ``parsed_json`` after the LLM
returns and before the caller uses it.

The redaction runs at the LLMProvider seam so every downstream
extractor benefits transparently — no per-callsite wiring, no
possibility of missing an extractor.
"""

from __future__ import annotations

from typing import Any

from providers.llm.base import LLMJsonResponse, LLMProvider
from semantic.redaction import redact_sensitive


def _redact_parsed_json_value(value: Any, *, visited: set[int] | None = None) -> Any:
    """Recursively redact string leaves in an LLM response payload.

    Mirrors :func:`core.service._redact_ingest_value` — same rules
    (redact values not keys, preserve container types, cycle-guard
    via ``visited`` set). Kept in a separate module to avoid a
    circular import between ``providers.llm`` and ``core.service``.
    """
    if isinstance(value, str):
        return redact_sensitive(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if visited is None:
        visited = set()
    obj_id = id(value)
    if obj_id in visited:
        return "[REDACTED CYCLE]"
    visited.add(obj_id)
    try:
        if isinstance(value, dict):
            return {
                k: _redact_parsed_json_value(v, visited=visited)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_redact_parsed_json_value(v, visited=visited) for v in value]
        if isinstance(value, tuple):
            return tuple(
                _redact_parsed_json_value(v, visited=visited) for v in value
            )
    finally:
        visited.discard(obj_id)
    return value


class RedactingLLMProviderWrapper(LLMProvider):
    """Wrap an :class:`LLMProvider` so every ``generate_json`` response
    passes through :func:`semantic.redaction.redact_sensitive`.

    Wrapping semantics:

    - ``parsed_json`` — every string leaf is redacted recursively.
      This is the field that flows into ``MemoryObject.payload`` and
      is the primary leak surface.
    - ``raw_text`` — also redacted, so any downstream consumer that
      falls back to parsing the raw string sees the same content.
    - ``metadata`` — passed through unchanged; provider metadata is
      never user-content-derived.

    Idempotent: wrapping an already-wrapped provider is safe (the
    underlying redaction is idempotent, so the outer wrapper's
    output equals the inner's).
    """

    def __init__(self, inner: LLMProvider):
        self._inner = inner

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str,
    ) -> LLMJsonResponse:
        response = self._inner.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=schema_description,
        )
        return LLMJsonResponse(
            raw_text=redact_sensitive(response.raw_text) if response.raw_text else response.raw_text,
            parsed_json=_redact_parsed_json_value(response.parsed_json) if response.parsed_json else response.parsed_json,
            metadata=response.metadata,
        )


__all__ = ["RedactingLLMProviderWrapper", "_redact_parsed_json_value"]
