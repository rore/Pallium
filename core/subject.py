"""Single source of truth for deriving a memory's subject from its payload.

`memory_objects.subject` is NULL across the production DB; the actual subject
text lives in `payload_json` and varies by memory type. This helper centralizes
the per-type dispatch so production gating, eval harnesses, and any future
consumer agree on what "the subject" of a memory is.

Pure function, no IO, no third-party dependencies.
"""
from __future__ import annotations

from typing import Any

_GENERIC_KEYS: tuple[str, ...] = ("subject", "title", "task", "statement")

_TYPE_KEYS: dict[str, tuple[str, ...]] = {
    "decision": ("decision",),
    "investigation_outcome": ("investigation_outcome", "outcome", "finding", "summary"),
    "constraint_memory": ("constraint_text", "summary"),
    "thread_summary": ("summary", "task", "current_state"),
    "turn_summary": ("summary", "task", "current_state"),
    "task_checkpoint": ("summary", "task", "current_state"),
    "fact_summary": ("summary", "task", "current_state"),
    "pattern_memory": ("summary", "statement"),
    "continuity_memory": ("summary", "statement"),
    "atomic_fact": ("statement", "summary"),
    "note": ("title", "content"),
}

_MAX_SUBJECT_LEN = 200


def _first_nonempty(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def subject_text_for_payload(item_type: str | None, payload: dict[str, Any] | None) -> str:
    """Return the subject text for a memory of `item_type` with `payload`.

    Lookup order:
      1. Generic keys (subject, title, task, statement) — these win across types.
      2. Per-type conventional keys (decision text, investigation outcome, etc.).
      3. Empty string when nothing matches.

    Result is stripped and capped at 200 chars.
    """
    if not payload:
        return ""
    found = _first_nonempty(payload, _GENERIC_KEYS)
    if not found:
        type_keys = _TYPE_KEYS.get(item_type or "", ())
        if type_keys:
            found = _first_nonempty(payload, type_keys)
    if not found:
        return ""
    return found[:_MAX_SUBJECT_LEN]
