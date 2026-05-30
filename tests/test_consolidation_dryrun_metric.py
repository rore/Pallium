"""Tests for the workstream-aware consolidation dry-run metric (Phase 4A).

Verifies the structural classification rules of
``capabilities.workstream_dryrun.emit_dryrun_metrics``. Kinds are
**neutral structural labels**, not quality verdicts (see module docstring):

* ``split_resolved_groups`` — old-key merged ≥2 facts; new-key splits them
  across ≥2 distinct resolved workstreams.
* ``single_workstream_group`` — old-key merged; new-key still merges
  (single workstream covers the group).
* ``split_with_unknown_or_overlap`` — old-key merged; new-key splits but at
  least one resulting subgroup contains an unknown pseudo-id.
* ``split_all_unknown`` — splits caused entirely by unknown pseudo-id
  partitioning.
* Anchor strategies emit ``workstream_homogeneity`` instead.

This test does NOT spin up the full BackgroundProcessor — it exercises
the dry-run module directly with synthetic candidates and a fake
metrics store.
"""
from __future__ import annotations

from datetime import datetime, timezone

from capabilities.consolidation import ConsolidationCandidate, ConsolidationGroup
from capabilities.workstream_dryrun import emit_dryrun_metrics
from capabilities.workstreams import WorkstreamCapability, WorkstreamStore
from core.models import MemoryObject


class _FakeMetricsStore:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, category: str, event_type: str, **kwargs) -> None:
        self.events.append({"category": category, "event_type": event_type, **kwargs})


class _StubStore(WorkstreamStore):
    """In-memory stub WorkstreamStore for unit tests."""

    def __init__(self, memory_assignments: dict[str, str]) -> None:
        self._mem_assignments = memory_assignments

    def get_memory_workstream_id(self, memory_object_id: str) -> str | None:
        return self._mem_assignments.get(memory_object_id)

    def get_latest_source_item_workstream_id(self, source_item_id: str) -> str | None:
        return None

    def upsert_workstream(self, **kwargs) -> None:
        return None

    def insert_source_item_workstream(self, **kwargs) -> None:
        return None

    def insert_memory_workstream(self, **kwargs) -> None:
        return None

    def list_open_workstreams(self, *, container_ref: str, visibility: str) -> list:
        return []


def _candidate(memory_id: str, *, subject: str = "subj", category: str = "fact") -> ConsolidationCandidate:
    mo = MemoryObject(
        type="atomic_fact",
        schema_id="test:fact",
        schema_version="1",
        payload={"subject": subject, "category": category, "statement": f"fact {memory_id}"},
        id=memory_id,
        container_ref="c1",
    )
    return ConsolidationCandidate(
        memory_object=mo,
        evidence=(),
        text_view=f"fact {memory_id}",
        tokens=frozenset(),
        container_ref="c1",
        thread_ref=f"thread-{memory_id}",
        latest_occurred_at=datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc),
        visibility="private",
    )


def _group(strategy: str, candidates: list[ConsolidationCandidate], **rationale) -> ConsolidationGroup:
    return ConsolidationGroup(
        strategy_name=strategy,
        strategy_version="v1",
        group_key=f"{strategy}:c1:subj:fact",
        candidates=tuple(candidates),
        container_ref="c1",
        thread_ref=None,
        latest_occurred_at=datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc),
        visibility="private",
        merge_rationale=rationale,
    )


def test_split_resolved_groups_when_two_resolved_ws_split_old_group():
    cands = [_candidate("m1"), _candidate("m2")]
    capability = WorkstreamCapability(
        _StubStore({"m1": "ws:aaa1", "m2": "ws:bbb2"})
    )
    store = _FakeMetricsStore()
    emit_dryrun_metrics(
        strategy_name="fact_consolidation",
        candidates=cands,
        groups=[_group("fact_consolidation", cands, subject="subj", category="fact")],
        workstream_capability=capability,
        metrics_store=store,
    )
    kinds = [e["payload"]["kind"] for e in store.events]
    assert "split_resolved_groups" in kinds


def test_single_workstream_group_when_one_workstream():
    cands = [_candidate("m1"), _candidate("m2"), _candidate("m3")]
    capability = WorkstreamCapability(
        _StubStore({"m1": "ws:same", "m2": "ws:same", "m3": "ws:same"})
    )
    store = _FakeMetricsStore()
    emit_dryrun_metrics(
        strategy_name="fact_consolidation",
        candidates=cands,
        groups=[_group("fact_consolidation", cands, subject="subj", category="fact")],
        workstream_capability=capability,
        metrics_store=store,
    )
    kinds = [e["payload"]["kind"] for e in store.events]
    assert kinds == ["single_workstream_group"]


def test_split_with_unknown_or_overlap_when_mix_of_resolved_and_unknown():
    cands = [_candidate("m1"), _candidate("m2")]
    # Only m1 resolved; m2 falls back to unknown pseudo-id (synthesized).
    capability = WorkstreamCapability(_StubStore({"m1": "ws:aaa"}))
    store = _FakeMetricsStore()
    emit_dryrun_metrics(
        strategy_name="fact_consolidation",
        candidates=cands,
        groups=[_group("fact_consolidation", cands, subject="subj", category="fact")],
        workstream_capability=capability,
        metrics_store=store,
    )
    kinds = [e["payload"]["kind"] for e in store.events]
    assert kinds == ["split_with_unknown_or_overlap"]


def test_split_all_unknown_when_all_unknown_but_distinct():
    cands = [_candidate("m1"), _candidate("m2")]
    # Neither m1 nor m2 resolved → both get distinct unknown pseudo-ids
    # (the synthesizer uses memory_object_id as disambiguator).
    capability = WorkstreamCapability(_StubStore({}))
    store = _FakeMetricsStore()
    emit_dryrun_metrics(
        strategy_name="fact_consolidation",
        candidates=cands,
        groups=[_group("fact_consolidation", cands, subject="subj", category="fact")],
        workstream_capability=capability,
        metrics_store=store,
    )
    kinds = [e["payload"]["kind"] for e in store.events]
    assert kinds == ["split_all_unknown"]


def test_anchor_strategy_emits_homogeneity():
    cands = [_candidate("m1"), _candidate("m2")]
    capability = WorkstreamCapability(_StubStore({"m1": "ws:same", "m2": "ws:same"}))
    store = _FakeMetricsStore()
    emit_dryrun_metrics(
        strategy_name="container_topic_window",
        candidates=cands,
        groups=[_group("container_topic_window", cands)],
        workstream_capability=capability,
        metrics_store=store,
    )
    assert any(e["event_type"] == "workstream_homogeneity" for e in store.events)
    payload = store.events[0]["payload"]
    assert payload["kind"] == "cluster_homogeneous"
    assert payload["n_resolved_ws"] == 1


def test_anchor_strategy_mixed_resolved():
    cands = [_candidate("m1"), _candidate("m2")]
    capability = WorkstreamCapability(_StubStore({"m1": "ws:a", "m2": "ws:b"}))
    store = _FakeMetricsStore()
    emit_dryrun_metrics(
        strategy_name="thread_summary_anchored",
        candidates=cands,
        groups=[_group("thread_summary_anchored", cands)],
        workstream_capability=capability,
        metrics_store=store,
    )
    assert store.events[0]["payload"]["kind"] == "cluster_mixed_resolved"


def test_no_emit_when_capability_or_metrics_missing():
    cands = [_candidate("m1"), _candidate("m2")]
    store = _FakeMetricsStore()
    # No capability → no-op, no events.
    emit_dryrun_metrics(
        strategy_name="fact_consolidation",
        candidates=cands,
        groups=[_group("fact_consolidation", cands)],
        workstream_capability=None,
        metrics_store=store,
    )
    assert store.events == []


def test_thread_local_carry_forward_payload_includes_thread_ref():
    cands = [_candidate("m1"), _candidate("m2")]
    capability = WorkstreamCapability(_StubStore({"m1": "ws:a", "m2": "ws:b"}))
    store = _FakeMetricsStore()
    grp = _group("thread_local_carry_forward", cands)
    # Override thread_ref to a real value so the payload check is meaningful.
    grp = ConsolidationGroup(
        strategy_name=grp.strategy_name,
        strategy_version=grp.strategy_version,
        group_key=grp.group_key,
        candidates=grp.candidates,
        container_ref=grp.container_ref,
        thread_ref="some-thread",
        latest_occurred_at=grp.latest_occurred_at,
        visibility=grp.visibility,
        merge_rationale=grp.merge_rationale,
    )
    emit_dryrun_metrics(
        strategy_name="thread_local_carry_forward",
        candidates=cands,
        groups=[grp],
        workstream_capability=capability,
        metrics_store=store,
    )
    assert store.events
    assert store.events[0]["payload"]["thread_ref"] == "some-thread"
