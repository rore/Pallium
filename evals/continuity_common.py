from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

CONTINUITY_FAILURE_FAMILIES = (
    "retrieval_recall_failure",
    "routing_layer_choice_failure",
    "result_packaging_evidence_failure",
    "compact_task_state_failure",
    "no_value_overreach_failure",
    "stale_memory_failure",
    "wrong_memory_selection_failure",
    "privacy_leak_failure",
)

HIGHER_LEVEL_LAYERS = {"pattern_memory", "continuity_memory", "task_checkpoint"}

FAILURE_FAMILY_TO_BOTTLENECK = {
    "retrieval_recall_failure": "retrieval_recall",
    "routing_layer_choice_failure": "routing",
    "result_packaging_evidence_failure": "evidence_packaging",
    "compact_task_state_failure": "task_state_packaging",
}

BOTTLENECK_IMPLICATIONS = {
    "retrieval_recall": "The current suite points to retrieval recall as the next tuning target before broader retrieval expansion.",
    "routing": "The current suite points to routing and layer choice as the next tuning target.",
    "evidence_packaging": "The current suite points to result and evidence packaging as the next tuning target.",
    "task_state_packaging": "The current suite points to compact task-state packaging as the next tuning target.",
}


def result_layer(item: dict[str, Any] | None) -> str:
    if item is None:
        return "none"
    if item.get("result_kind") == "source_hit":
        return "source_evidence"
    if item.get("type") == "pattern_memory":
        return "pattern_memory"
    if item.get("type") == "continuity_memory":
        return "continuity_memory"
    if item.get("type") == "task_checkpoint":
        return "task_checkpoint"
    return "lower_level_memory"


def failure_family_counts(rows: Iterable[dict[str, Any]], key: str = "failure_families") -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row.get(key, []))
    return {name: int(counts.get(name, 0)) for name in CONTINUITY_FAILURE_FAMILIES}


def dominant_tuning_bottleneck(counts: dict[str, int]) -> str | list[str] | None:
    bottleneck_counts: Counter[str] = Counter()
    for family, count in counts.items():
        bottleneck = FAILURE_FAMILY_TO_BOTTLENECK.get(family)
        if bottleneck and count > 0:
            bottleneck_counts[bottleneck] += count
    if not bottleneck_counts:
        return None
    highest = max(bottleneck_counts.values())
    winners = sorted(name for name, count in bottleneck_counts.items() if count == highest)
    if len(winners) == 1:
        return winners[0]
    return winners


def dominant_bottleneck_implication(bottleneck: str | list[str] | None) -> str | None:
    if bottleneck is None:
        return None
    if isinstance(bottleneck, list):
        return "Multiple tuning bottlenecks tied in the current suite, so the next change should stay benchmark-guided rather than assuming one dominant gap."
    return BOTTLENECK_IMPLICATIONS.get(bottleneck)
