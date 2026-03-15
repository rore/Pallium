from __future__ import annotations

from datetime import timedelta
from typing import Any

from core.observability import OBSERVABILITY_METADATA_KEY
from semantic.common import SEMANTIC_SIGNAL_METADATA_KEY


RETENTION_MAINTENANCE_KEY = "retention_compaction"
DURABLE_MEMORY_TYPES = frozenset({"decision", "investigation_outcome"})
FRESH_WORKING_MEMORY_TYPES = frozenset({"thread_summary", "task_checkpoint", "continuity_memory", "pattern_memory"})
ORPHAN_DELETE_MEMORY_TYPES = frozenset({"discussion_summary"})

SUPERSEDED_MEMORY_TTL = timedelta(days=7)
WORKING_MEMORY_TTL = timedelta(days=30)
LOW_VALUE_RAW_TTL = timedelta(days=3)
ORDINARY_RAW_TTL = timedelta(days=30)
WORK_ARTIFACT_RAW_TTL = timedelta(days=45)
DEBUG_METADATA_TTL = timedelta(days=3)


def source_item_retention_ttl(*, artifact_kind: str | None, metadata: dict[str, Any] | None) -> timedelta:
    normalized_artifact_kind = (artifact_kind or "").strip().lower()
    if normalized_artifact_kind in {"tool_use_summary", "todo_snapshot"}:
        return WORK_ARTIFACT_RAW_TTL
    if normalized_artifact_kind in {"message", "assistant_output"} and is_low_value_meta_source(metadata):
        return LOW_VALUE_RAW_TTL
    return ORDINARY_RAW_TTL


def is_low_value_meta_source(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    signals = metadata.get(SEMANTIC_SIGNAL_METADATA_KEY)
    if isinstance(signals, dict) and signals.get("is_low_value_meta") is True:
        return True
    observability = metadata.get(OBSERVABILITY_METADATA_KEY)
    if isinstance(observability, dict):
        semantic_signals = observability.get("semantic_signals")
        if isinstance(semantic_signals, dict) and semantic_signals.get("is_low_value_meta") is True:
            return True
    return False
