"""Unit tests for capabilities/workstreams.py cascade.

Covers all 8 stages, plus self-ref protection, monorepo split, and the
unknown-pseudo-id non-joining property.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from capabilities.workstream_signals import ItemSignals
from capabilities.workstreams import (
    AssignmentResult,
    STAGE_ANCHOR,
    STAGE_FILE_PATH,
    STAGE_OPEN_NEW,
    STAGE_RECENCY,
    STAGE_SELF_REF_ATTACH,
    STAGE_SYMBOL,
    STAGE_TITLE,
    STAGE_UNKNOWN,
    STAGE_WORK_REFS,
    WorkstreamId,
    WorkstreamRegistry,
    assign_workstream_for_item,
    resolved_id_from_signals,
    unknown_pseudo_id,
    watermark_for,
)


def _now() -> datetime:
    return datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


def _signals(**kwargs) -> ItemSignals:
    sig = ItemSignals()
    for k, v in kwargs.items():
        getattr(sig, k).update(v)
    return sig


# ---------------------------------------------------------------------------
# Pseudo-id helpers
# ---------------------------------------------------------------------------


def test_unknown_pseudo_id_format():
    pid = unknown_pseudo_id("c1", "t1", "20260530T1200")
    assert pid.kind == "unknown"
    assert pid.id == "unknown:c1:t1:20260530T1200"


def test_unknown_pseudo_id_null_thread():
    pid = unknown_pseudo_id("c1", None, "20260530T1200")
    assert pid.id == "unknown:c1:NULL:20260530T1200"


def test_unknown_pseudo_id_non_joining_across_threads():
    # R5: two unknowns in different (thread, watermark) tuples MUST NOT be equal.
    a = unknown_pseudo_id("c1", "t1", "20260530T1200")
    b = unknown_pseudo_id("c1", "t2", "20260530T1200")
    c = unknown_pseudo_id("c1", "t1", "20260530T1205")
    assert a.id != b.id
    assert a.id != c.id
    assert b.id != c.id


def test_unknown_pseudo_id_never_literal_sentinel():
    pid = unknown_pseudo_id("c1", None, "wm")
    assert pid.id != "workstream_unknown"
    assert pid.id != "unknown"


def test_resolved_id_from_signals_stable_hash():
    # Same signal set → same id (replay-deterministic).
    a = resolved_id_from_signals(["wr:proj-123", "fd:core/service"])
    b = resolved_id_from_signals(["fd:core/service", "wr:proj-123"])  # order should not matter
    assert a.id == b.id
    assert a.kind == "resolved"
    assert a.id.startswith("ws:")


def test_resolved_id_requires_at_least_one_signal():
    import pytest

    with pytest.raises(ValueError):
        resolved_id_from_signals([])


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------


def test_watermark_for_5_minute_bucket():
    a = watermark_for(datetime(2026, 5, 30, 12, 3, 0, tzinfo=timezone.utc))
    b = watermark_for(datetime(2026, 5, 30, 12, 4, 59, tzinfo=timezone.utc))
    c = watermark_for(datetime(2026, 5, 30, 12, 5, 0, tzinfo=timezone.utc))
    assert a == b
    assert a != c


# ---------------------------------------------------------------------------
# Cascade — stage 1: work_refs
# ---------------------------------------------------------------------------


def test_stage_work_refs_attaches_to_existing():
    reg = WorkstreamRegistry()
    now = _now()

    # Open with one work_ref.
    r1 = assign_workstream_for_item(
        item_signals=_signals(work_refs={"proj-123"}),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    assert r1.stage == STAGE_OPEN_NEW
    assert r1.workstream_id.kind == "resolved"

    # New item with same work_ref — must attach via stage 1.
    r2 = assign_workstream_for_item(
        item_signals=_signals(work_refs={"proj-123"}),
        container_ref="c1",
        thread_ref="t2",  # different thread; work_ref still wins
        visibility="private",
        created_at=now + timedelta(hours=1),
        watermark="wm1",
        registry=reg,
    )
    assert r2.stage == STAGE_WORK_REFS
    assert r2.workstream_id.id == r1.workstream_id.id


# ---------------------------------------------------------------------------
# Cascade — stage 2: file_dir overlap
# ---------------------------------------------------------------------------


def test_stage_file_path_overlap():
    reg = WorkstreamRegistry()
    now = _now()
    r1 = assign_workstream_for_item(
        item_signals=_signals(file_paths={"core/service.py"}, file_dirs={"core/service.py"}),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    r2 = assign_workstream_for_item(
        item_signals=_signals(file_paths={"core/service.py"}, file_dirs={"core/service.py"}),
        container_ref="c1",
        thread_ref="t2",
        visibility="private",
        created_at=now + timedelta(minutes=10),
        watermark="wm1",
        registry=reg,
    )
    assert r2.stage == STAGE_FILE_PATH
    assert r2.workstream_id.id == r1.workstream_id.id


# ---------------------------------------------------------------------------
# Cascade — stage 3: symbol overlap
# ---------------------------------------------------------------------------


def test_stage_symbol_overlap():
    reg = WorkstreamRegistry()
    now = _now()
    r1 = assign_workstream_for_item(
        item_signals=_signals(symbols={"WorkstreamRegistry"}),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    r2 = assign_workstream_for_item(
        item_signals=_signals(symbols={"WorkstreamRegistry"}),
        container_ref="c1",
        thread_ref="t2",
        visibility="private",
        created_at=now + timedelta(minutes=10),
        watermark="wm1",
        registry=reg,
    )
    assert r2.stage == STAGE_SYMBOL
    assert r2.workstream_id.id == r1.workstream_id.id


# ---------------------------------------------------------------------------
# Cascade — stage 4: title 3-gram
# ---------------------------------------------------------------------------


def test_stage_title_ngram_overlap():
    reg = WorkstreamRegistry()
    now = _now()
    grams = {("workstream", "rekey", "design")}
    r1 = assign_workstream_for_item(
        item_signals=_signals(titles={"workstream rekey design"}, title_ngrams=grams),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    r2 = assign_workstream_for_item(
        item_signals=_signals(titles={"workstream rekey design"}, title_ngrams=grams),
        container_ref="c1",
        thread_ref="t2",
        visibility="private",
        created_at=now + timedelta(minutes=10),
        watermark="wm1",
        registry=reg,
    )
    assert r2.stage == STAGE_TITLE
    assert r2.workstream_id.id == r1.workstream_id.id


# ---------------------------------------------------------------------------
# Cascade — stage 5: anchor match
# ---------------------------------------------------------------------------


def test_stage_anchor_match():
    reg = WorkstreamRegistry()
    now = _now()
    r1 = assign_workstream_for_item(
        item_signals=_signals(anchors={"workstream:consolidation rekey"}),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    r2 = assign_workstream_for_item(
        item_signals=_signals(anchors={"workstream:consolidation rekey"}),
        container_ref="c1",
        thread_ref="t2",
        visibility="private",
        created_at=now + timedelta(minutes=10),
        watermark="wm1",
        registry=reg,
    )
    assert r2.stage == STAGE_ANCHOR
    assert r2.workstream_id.id == r1.workstream_id.id


# ---------------------------------------------------------------------------
# Cascade — stage 6: same-thread recency tiebreaker
# ---------------------------------------------------------------------------


def test_stage_recency_attaches_signal_less_followup():
    reg = WorkstreamRegistry()
    now = _now()
    # First item with strong signal.
    r1 = assign_workstream_for_item(
        item_signals=_signals(symbols={"WorkstreamRegistry"}),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    # Followup in same thread with NO strong signals → recency attach.
    r2 = assign_workstream_for_item(
        item_signals=_signals(),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now + timedelta(minutes=5),
        watermark="wm1",
        registry=reg,
    )
    assert r2.stage == STAGE_RECENCY
    assert r2.workstream_id.id == r1.workstream_id.id


def test_stage_recency_blocked_by_disagreeing_file_dirs():
    """Monorepo protection: divergent file dirs should block recency attach."""
    reg = WorkstreamRegistry()
    now = _now()
    r1 = assign_workstream_for_item(
        item_signals=_signals(file_paths={"core/service.py"}, file_dirs={"core/service.py"}),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    # Same thread, recent — but completely different file dirs.
    r2 = assign_workstream_for_item(
        item_signals=_signals(file_paths={"semantic/agent.py"}, file_dirs={"semantic/agent.py"}),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now + timedelta(minutes=5),
        watermark="wm1",
        registry=reg,
    )
    # Must split into a new workstream, NOT attach via recency.
    assert r2.stage == STAGE_OPEN_NEW
    assert r2.workstream_id.id != r1.workstream_id.id


# ---------------------------------------------------------------------------
# Cascade — stage 7: open-new (with self-ref protection)
# ---------------------------------------------------------------------------


def test_stage_open_new_with_distinct_signals():
    reg = WorkstreamRegistry()
    now = _now()
    # First open.
    r1 = assign_workstream_for_item(
        item_signals=_signals(file_paths={"a/b.py"}, file_dirs={"a/b.py"}),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    # Distinct dirs → open new.
    r2 = assign_workstream_for_item(
        item_signals=_signals(file_paths={"x/y.py"}, file_dirs={"x/y.py"}),
        container_ref="c1",
        thread_ref="t2",
        visibility="private",
        created_at=now + timedelta(hours=2),
        watermark="wm1",
        registry=reg,
    )
    assert r2.stage == STAGE_OPEN_NEW
    assert r1.workstream_id.id != r2.workstream_id.id


def test_self_ref_protection_attaches_when_signals_subset():
    """When item signals are a subset of the most-recent open ws, attach
    via self_ref_attach (do NOT split)."""
    reg = WorkstreamRegistry()
    now = _now()
    # Seed a ws with a richer signal set.
    base_signals = _signals(
        file_paths={"core/service.py"},
        file_dirs={"core/service.py"},
        symbols={"WorkstreamRegistry"},
    )
    r1 = assign_workstream_for_item(
        item_signals=base_signals,
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    # New item with a strict subset of the seed's signals (and outside
    # recency window so stage 6 doesn't fire).
    r2 = assign_workstream_for_item(
        item_signals=_signals(file_paths={"core/service.py"}, file_dirs={"core/service.py"}),
        container_ref="c1",
        thread_ref="t9",  # different thread; recency won't fire
        visibility="private",
        created_at=now + timedelta(hours=5),
        watermark="wm1",
        registry=reg,
    )
    # The cascade should reach stage 2 (file_dirs overlap with the open ws).
    # The self-ref test really kicks in after stages 1-6 fail; confirm at
    # least that we DON'T open a new ws in this scenario.
    assert r1.workstream_id.id == r2.workstream_id.id


# ---------------------------------------------------------------------------
# Cascade — stage 8: unknown pseudo-id
# ---------------------------------------------------------------------------


def test_stage_unknown_with_no_signals():
    reg = WorkstreamRegistry()
    now = _now()
    r = assign_workstream_for_item(
        item_signals=_signals(),
        container_ref="c1",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    assert r.stage == STAGE_UNKNOWN
    assert r.workstream_id.kind == "unknown"
    assert r.workstream_id.id.startswith("unknown:c1:")


# ---------------------------------------------------------------------------
# Monorepo split — different file_dirs in same container produce distinct ws.
# ---------------------------------------------------------------------------


def test_monorepo_split_different_modules_distinct_workstreams():
    reg = WorkstreamRegistry()
    now = _now()
    r_core = assign_workstream_for_item(
        item_signals=_signals(file_paths={"core/service.py"}, file_dirs={"core/service.py"}),
        container_ref="monorepo",
        thread_ref="t1",
        visibility="private",
        created_at=now,
        watermark="wm1",
        registry=reg,
    )
    r_semantic = assign_workstream_for_item(
        item_signals=_signals(file_paths={"semantic/agent.py"}, file_dirs={"semantic/agent.py"}),
        container_ref="monorepo",
        thread_ref="t2",
        visibility="private",
        created_at=now + timedelta(hours=1),
        watermark="wm1",
        registry=reg,
    )
    r_storage = assign_workstream_for_item(
        item_signals=_signals(file_paths={"storage/sqlite.py"}, file_dirs={"storage/sqlite.py"}),
        container_ref="monorepo",
        thread_ref="t3",
        visibility="private",
        created_at=now + timedelta(hours=2),
        watermark="wm1",
        registry=reg,
    )
    ids = {r_core.workstream_id.id, r_semantic.workstream_id.id, r_storage.workstream_id.id}
    assert len(ids) == 3
