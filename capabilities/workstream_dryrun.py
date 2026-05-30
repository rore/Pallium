"""Workstream-aware consolidation dry-run metric (Phase 4A, design 014).

Behavior is unchanged — the existing strategies still group by their
existing key. This module computes the *new* key (with workstream id
inserted as an additional dimension) on the same candidates, classifies
the structural difference per group, and emits a metric per group via
:class:`storage.metrics.MetricsStore`.

Two metric streams are emitted, depending on strategy shape:

* Fixed-key strategies (``thread_local_carry_forward``,
  ``fact_consolidation``) emit ``consolidation.workstream_aware_dryrun``
  with kinds ``bad_merge_avoided`` / ``good_merge_preserved`` /
  ``good_merge_lost_suspected`` / ``novel_split_unknown``.
* Anchor-based strategies (``container_topic_window``,
  ``thread_summary_anchored``) emit
  ``consolidation.workstream_homogeneity`` with kinds
  ``cluster_homogeneous`` / ``cluster_mixed_resolved`` /
  ``cluster_mixed_unknown``.

No LLM call. No network call. Purely structural.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

from capabilities.consolidation import ConsolidationCandidate, ConsolidationGroup
from capabilities.workstreams import WorkstreamCapability, unknown_pseudo_id, watermark_for


_logger = logging.getLogger(__name__)


_FIXED_KEY_STRATEGIES = {
    "thread_local_carry_forward",
    "fact_consolidation",
}

_ANCHOR_STRATEGIES = {
    "container_topic_window",
    "thread_summary_anchored",
}


def _resolve_candidate_ws_id(
    candidate: ConsolidationCandidate,
    capability: WorkstreamCapability,
) -> str:
    """Look up the workstream id for a candidate.

    Falls back to a unique unknown pseudo-id (per source item) if no
    workstream is recorded — preserves the non-joining property without
    requiring a recorded ``source_item_workstreams`` row.
    """
    memory_id = candidate.memory_object.id
    looked_up = capability.lookup_memory(memory_id)
    if looked_up:
        return looked_up
    # Synthesize a pseudo-id for the candidate — non-joining because we use
    # the memory_object_id as the disambiguator. This preserves R5: two
    # unknowns never compare equal.
    container_ref = candidate.container_ref or "unknown"
    thread_ref = candidate.thread_ref or "NULL"
    wm = watermark_for(candidate.latest_occurred_at)
    # The memory id provides additional disambiguation so that two memories
    # in the same (container, thread, watermark) bucket without recorded
    # workstreams still get distinct pseudo-ids.
    return f"unknown:{container_ref}:{thread_ref}:{wm}:{memory_id}"


def emit_dryrun_metrics(
    *,
    strategy_name: str,
    candidates: list[ConsolidationCandidate],
    groups: list[ConsolidationGroup],
    workstream_capability: WorkstreamCapability | None,
    metrics_store,
) -> None:
    """Compute new-key groupings and emit dry-run metrics.

    No-op when either the workstream capability or metrics store is
    unavailable — the metric is best-effort observability.
    """
    if workstream_capability is None or metrics_store is None:
        return
    try:
        if strategy_name in _FIXED_KEY_STRATEGIES:
            _emit_fixed_key_dryrun(
                strategy_name=strategy_name,
                groups=groups,
                workstream_capability=workstream_capability,
                metrics_store=metrics_store,
            )
        elif strategy_name in _ANCHOR_STRATEGIES:
            _emit_anchor_homogeneity(
                strategy_name=strategy_name,
                groups=groups,
                workstream_capability=workstream_capability,
                metrics_store=metrics_store,
            )
    except Exception:
        _logger.warning("workstream dryrun metric emission failed", exc_info=True)


def _emit_fixed_key_dryrun(
    *,
    strategy_name: str,
    groups: list[ConsolidationGroup],
    workstream_capability: WorkstreamCapability,
    metrics_store,
) -> None:
    """Per-group, classify the structural diff old-key vs new-key (with
    workstream id inserted)."""
    for group in groups:
        old_size = len(group.candidates)
        # New-key partitioning: split this group's members by ws_id.
        partitions: dict[str, list[ConsolidationCandidate]] = {}
        for cand in group.candidates:
            ws_id = _resolve_candidate_ws_id(cand, workstream_capability)
            partitions.setdefault(ws_id, []).append(cand)

        partition_ws_ids = list(partitions.keys())
        resolved_ws_ids = [w for w in partition_ws_ids if not w.startswith("unknown:")]
        unknown_ws_ids = [w for w in partition_ws_ids if w.startswith("unknown:")]
        # New-key "merged" group equals the largest single partition. We
        # report new_group_size as the size of that largest partition.
        largest_partition = max(partitions.values(), key=len)
        new_size = len(largest_partition)

        kind = _classify_fixed_key(
            old_size=old_size,
            partitions=partitions,
            resolved_ws_ids=resolved_ws_ids,
            unknown_ws_ids=unknown_ws_ids,
        )
        if kind is None:
            continue

        payload: dict = {
            "strategy": strategy_name,
            "kind": kind,
            "old_group_size": old_size,
            "new_group_size": new_size,
            "container_ref": group.container_ref,
        }
        merge_rationale = group.merge_rationale or {}
        if strategy_name == "fact_consolidation":
            payload["subject"] = merge_rationale.get("subject")
            payload["category"] = merge_rationale.get("category")
        elif strategy_name == "thread_local_carry_forward":
            payload["thread_ref"] = group.thread_ref

        metrics_store.record(
            "consolidation",
            "workstream_aware_dryrun",
            container_ref=group.container_ref,
            thread_ref=group.thread_ref,
            payload=payload,
        )


def _classify_fixed_key(
    *,
    old_size: int,
    partitions: dict[str, list[ConsolidationCandidate]],
    resolved_ws_ids: list[str],
    unknown_ws_ids: list[str],
) -> str | None:
    """Structural classification for fixed-key strategies.

    Returns the kind, or ``None`` if the group is too small to produce a
    meaningful merge signal (size < 2).
    """
    if old_size < 2:
        return None
    if len(partitions) <= 1:
        return "good_merge_preserved"
    # Multiple partitions → split.
    if len(resolved_ws_ids) >= 2 and not unknown_ws_ids:
        return "bad_merge_avoided"
    if unknown_ws_ids and not resolved_ws_ids:
        return "novel_split_unknown"
    # Mixed: at least one unknown bucket and at least one resolved.
    return "good_merge_lost_suspected"


def _emit_anchor_homogeneity(
    *,
    strategy_name: str,
    groups: list[ConsolidationGroup],
    workstream_capability: WorkstreamCapability,
    metrics_store,
) -> None:
    for group in groups:
        ws_ids = [
            _resolve_candidate_ws_id(c, workstream_capability) for c in group.candidates
        ]
        resolved = {w for w in ws_ids if not w.startswith("unknown:")}
        unknown_buckets = {w for w in ws_ids if w.startswith("unknown:")}
        n_resolved = len(resolved)
        n_unknown = len(unknown_buckets)
        if n_resolved == 1 and n_unknown == 0:
            kind = "cluster_homogeneous"
        elif n_resolved >= 2 and n_unknown == 0:
            kind = "cluster_mixed_resolved"
        else:
            kind = "cluster_mixed_unknown"
        payload = {
            "strategy": strategy_name,
            "kind": kind,
            "cluster_size": len(ws_ids),
            "n_resolved_ws": n_resolved,
            "n_unknown_buckets": n_unknown,
            "container_ref": group.container_ref,
        }
        metrics_store.record(
            "consolidation",
            "workstream_homogeneity",
            container_ref=group.container_ref,
            thread_ref=group.thread_ref,
            payload=payload,
        )
