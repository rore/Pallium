"""Work-reference normalization.

A `work_ref` is an opaque identifier callers attach to source items so the
agent can resolve them back to a logical workstream (a ticket id, a file
path slug, a feature codename). Inputs come from heterogeneous sources
(LLM outputs, query parameters, agent prompts) so we casefold and collapse
separators to a single canonical form before storing or comparing.

Lives in `core/` because it has no semantic-package dependencies and is
imported by `api/`, `semantic/`, and `capabilities/` alike.
"""

from __future__ import annotations

import re
from typing import Any

_WORK_REF_SEPARATOR_RE = re.compile(r"[\s_\-]+")
MAX_WORK_REFS = 5


def _normalize_work_ref(raw: str) -> str | None:
    """Normalize a single work reference identifier.

    Casefolds and collapses whitespace/underscores/hyphens to a single hyphen.
    Returns None if empty or too long.
    """
    value = raw.strip().casefold()
    if not value or len(value) > 128:
        return None
    value = _WORK_REF_SEPARATOR_RE.sub("-", value).strip("-")
    return value if value else None


def _normalize_work_refs(value: Any) -> tuple[str, ...]:
    """Normalize and deduplicate a list of work reference identifiers from LLM output."""
    if value is None:
        return ()
    if not isinstance(value, list):
        return ()
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = _normalize_work_ref(item)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) == MAX_WORK_REFS:
            break
    return tuple(result)
