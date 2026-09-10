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

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from redaction import redact_sensitive

_WORK_REF_SEPARATOR_RE = re.compile(r"[\s_\-]+")
MAX_WORK_REFS = 5
_WORK_KEY_RE = re.compile(r"^work:v1:[0-9a-f]{64}$")
_ASCII_WHITESPACE = " \t\n\r\f\v"

@dataclass(frozen=True)
class ReadableWorkRef:
    scope_ref: str
    local_ref: str
    key: str

def _validate_readable_part(value: Any, *, local: bool) -> str:
    if not isinstance(value, str) or not value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError("work identity must contain well-formed Unicode text")
    value = unicodedata.normalize("NFC", value)
    if not value or value[0] in _ASCII_WHITESPACE or value[-1] in _ASCII_WHITESPACE:
        raise ValueError("work identity must not have leading or trailing ASCII whitespace")
    if any(ord(c) <= 0x1F or 0x7F <= ord(c) <= 0x9F or ord(c) in (0x2028, 0x2029) for c in value):
        raise ValueError("work identity contains a control character")
    if "[REDACTED" in value or redact_sensitive(value) != value:
        raise ValueError("work identity contains redacted or secret material")
    encoded = value.encode("utf-8")
    if len(encoded) > 512 or (local and len(value) > 128):
        raise ValueError("work identity exceeds its bound")
    return value

def readable_work_ref(scope_ref: str, local_ref: str) -> ReadableWorkRef:
    scope = _validate_readable_part(scope_ref, local=False)
    local = _validate_readable_part(local_ref, local=True)
    digest = hashlib.sha256(scope.encode("utf-8") + b"\0" + local.encode("utf-8")).hexdigest()
    return ReadableWorkRef(scope, local, f"work:v1:{digest}")

def validate_work_ref_key(value: str) -> str:
    if not isinstance(value, str) or not _WORK_KEY_RE.fullmatch(value):
        raise ValueError("invalid advanced work reference key")
    return value


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


def work_refs_from_metadata(metadata: Any) -> tuple[str, ...]:
    """Safely project legacy metadata into normalized work references."""
    if not isinstance(metadata, dict):
        return ()
    value = metadata.get("pallium_work_refs")
    if not isinstance(value, list):
        return ()
    safe = [
        item
        for item in value
        if isinstance(item, str)
        and "\x00" not in item
        and "[REDACTED" not in item
        and redact_sensitive(item) == item
    ]
    return _normalize_work_refs(safe)
