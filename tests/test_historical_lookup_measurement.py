"""Unit tests for evals/historical_lookup_measurement.py.

Covers:
- Three-rung math on synthetic sessions/events: exact per-100 values, monotonic
- Empty-data safety: 0 eligible sessions → nulls + note, no exception
- Wilson interval: bounds in [0, 100], low <= point <= high, one hand-checked value
- Dedup: a session with 2 events at the same rung counts once in the numerator
- Loader stub: load_events_from_storage returns empty lists without error
"""

from __future__ import annotations

import pytest

from evals.historical_lookup_measurement import (
    _wilson_95,
    compute_reuse_rollup,
    load_events_from_storage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_window() -> dict:
    return {"since": "2026-08-01T00:00:00Z", "until": "2026-08-13T00:00:00Z"}


# ---------------------------------------------------------------------------
# Three-rung math
# ---------------------------------------------------------------------------


class TestThreeRungMath:
    """Exact per-100 values and monotonic rungs on synthetic data."""

    def test_exact_per_100_values(self) -> None:
        # 10 eligible sessions, 6 incorporation, 4 influence, 1 downstream
        sessions = [str(i) for i in range(10)]
        events = (
            [{"session_id": str(i), "rung": "incorporation"} for i in range(6)]
            + [{"session_id": str(i), "rung": "influence"} for i in range(4)]
            + [{"session_id": "0", "rung": "downstream"}]
        )
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window=_make_window()
        )

        inc = result["rungs"]["incorporation"]
        inf = result["rungs"]["influence"]
        dwn = result["rungs"]["downstream"]

        assert inc["numerator"] == 6
        assert inc["denominator"] == 10
        assert inc["reuse_per_100_eligible"] == pytest.approx(60.0)

        assert inf["numerator"] == 4
        assert inf["denominator"] == 10
        assert inf["reuse_per_100_eligible"] == pytest.approx(40.0)

        assert dwn["numerator"] == 1
        assert dwn["denominator"] == 10
        assert dwn["reuse_per_100_eligible"] == pytest.approx(10.0)

    def test_monotonic_rungs(self) -> None:
        """Under the typical shaped-funnel assumption, rungs are non-increasing."""
        sessions = [str(i) for i in range(10)]
        events = (
            [{"session_id": str(i), "rung": "incorporation"} for i in range(6)]
            + [{"session_id": str(i), "rung": "influence"} for i in range(4)]
            + [{"session_id": "0", "rung": "downstream"}]
        )
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window=_make_window()
        )
        rungs = result["rungs"]
        assert (
            rungs["incorporation"]["reuse_per_100_eligible"]
            >= rungs["influence"]["reuse_per_100_eligible"]
            >= rungs["downstream"]["reuse_per_100_eligible"]
        )

    def test_labels_and_measures(self) -> None:
        """Each rung carries the correct label and measures annotation."""
        sessions = ["s1"]
        events = [{"session_id": "s1", "rung": "incorporation"}]
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window={}
        )
        inc = result["rungs"]["incorporation"]
        inf = result["rungs"]["influence"]
        dwn = result["rungs"]["downstream"]

        assert "rung-1" in inc["label"]
        assert inc["measures"] == "downstream-task-effect"
        assert inc["claim"] == "observational"

        assert "rung-2" in inf["label"]
        assert inf["measures"] == "downstream-task-effect"
        assert inf["claim"] == "observational"

        assert "rung-3" in dwn["label"]
        assert dwn["measures"] == "downstream-task-effect"
        assert dwn["claim"] == "controlled"

    def test_top_level_fields(self) -> None:
        result = compute_reuse_rollup(
            ["s0"], [], eligibility_n=50, window={"since": "2026-08-01"}
        )
        assert result["eligibility_n"] == 50
        assert result["n_eligible_sessions"] == 1
        assert result["n_reuse_events"] == 0
        assert "spec" in result

    def test_events_from_non_eligible_sessions_are_ignored(self) -> None:
        sessions = ["s1", "s2"]
        events = [
            {"session_id": "s_other", "rung": "incorporation"},  # not eligible
            {"session_id": "s1", "rung": "incorporation"},
        ]
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window={}
        )
        assert result["rungs"]["incorporation"]["numerator"] == 1


# ---------------------------------------------------------------------------
# Empty-data safety
# ---------------------------------------------------------------------------


class TestEmptyDataSafety:
    """0 eligible sessions must produce nulls + note, never raise."""

    def test_zero_eligible_sessions_no_exception(self) -> None:
        result = compute_reuse_rollup(
            [], [], eligibility_n=50, window=_make_window()
        )
        assert result["n_eligible_sessions"] == 0

    def test_zero_eligible_all_rungs_null(self) -> None:
        result = compute_reuse_rollup(
            [], [], eligibility_n=50, window=_make_window()
        )
        for rung_key, rung in result["rungs"].items():
            assert rung["reuse_per_100_eligible"] is None, rung_key
            assert rung["wilson_95"]["low"] is None, rung_key
            assert rung["wilson_95"]["high"] is None, rung_key

    def test_zero_eligible_note_text(self) -> None:
        result = compute_reuse_rollup(
            [], [], eligibility_n=50, window={}
        )
        for rung_key, rung in result["rungs"].items():
            assert "n/a (0 eligible)" in rung.get("note", ""), rung_key

    def test_zero_eligible_with_spurious_events(self) -> None:
        """Events whose sessions aren't eligible must not bypass the guard."""
        result = compute_reuse_rollup(
            [],
            [{"session_id": "ghost", "rung": "incorporation"}],
            eligibility_n=50,
            window={},
        )
        assert result["rungs"]["incorporation"]["reuse_per_100_eligible"] is None

    def test_empty_events_with_eligible_sessions(self) -> None:
        """Eligible sessions but no events → 0.0, not null."""
        sessions = ["s1", "s2", "s3"]
        result = compute_reuse_rollup(
            sessions, [], eligibility_n=50, window={}
        )
        for rung_key, rung in result["rungs"].items():
            assert rung["reuse_per_100_eligible"] == pytest.approx(0.0), rung_key
            assert rung["numerator"] == 0


# ---------------------------------------------------------------------------
# Wilson interval
# ---------------------------------------------------------------------------


class TestWilsonInterval:
    """Bounds in [0, 100], low <= point <= high, hand-checked value."""

    def test_bounds_in_range(self) -> None:
        low, high = _wilson_95(6, 10)
        assert 0.0 <= low <= 1.0
        assert 0.0 <= high <= 1.0
        assert low <= high

    def test_point_within_interval(self) -> None:
        """The sample proportion must lie within its Wilson interval."""
        for k, n in [(0, 10), (1, 10), (5, 10), (6, 10), (10, 10), (3, 30)]:
            low, high = _wilson_95(k, n)
            p = k / n
            assert low <= p <= high, f"k={k}, n={n}: p={p} not in [{low}, {high}]"

    def test_hand_checked_value(self) -> None:
        """k=6, n=10, z=1.96 → low≈0.3127, high≈0.8318.

        Derivation:
            p=0.6, z²=3.8416
            center = (0.6 + 0.19208) / 1.38416 ≈ 0.57227
            margin = 1.96·√(0.033604) / 1.38416 ≈ 0.25958
            low  ≈ 0.31269   high ≈ 0.83185
        """
        low, high = _wilson_95(6, 10)
        assert abs(low - 0.31269) < 0.001
        assert abs(high - 0.83185) < 0.001

    def test_per100_interval_in_report(self) -> None:
        """Wilson values in the rollup output are per-100 scaled and consistent."""
        sessions = [str(i) for i in range(10)]
        events = [{"session_id": str(i), "rung": "incorporation"} for i in range(6)]
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window={}
        )
        inc = result["rungs"]["incorporation"]
        rate = inc["reuse_per_100_eligible"]
        low = inc["wilson_95"]["low"]
        high = inc["wilson_95"]["high"]

        assert 0.0 <= low <= 100.0
        assert 0.0 <= high <= 100.0
        assert low <= rate <= high

    def test_wilson_zero_numerator(self) -> None:
        """0/n: low must be 0, high > 0 (interval is one-sided)."""
        low, high = _wilson_95(0, 20)
        assert low == pytest.approx(0.0, abs=1e-9)
        assert high > 0.0

    def test_wilson_full_numerator(self) -> None:
        """n/n: high must be 1.0, low < 1.0."""
        low, high = _wilson_95(20, 20)
        assert high == pytest.approx(1.0, abs=1e-9)
        assert low < 1.0

    def test_wilson_raises_on_zero_denominator(self) -> None:
        with pytest.raises(ValueError):
            _wilson_95(0, 0)


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


class TestDedup:
    """A session with multiple events at the same rung counts once."""

    def test_duplicate_events_same_rung(self) -> None:
        sessions = ["s1", "s2", "s3"]
        events = [
            {"session_id": "s1", "rung": "incorporation"},
            {"session_id": "s1", "rung": "incorporation"},  # duplicate
            {"session_id": "s1", "rung": "incorporation"},  # duplicate
            {"session_id": "s2", "rung": "incorporation"},
        ]
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window={}
        )
        inc = result["rungs"]["incorporation"]
        # s1 counted once; s2 once; s3 no event → numerator = 2
        assert inc["numerator"] == 2
        assert inc["reuse_per_100_eligible"] == pytest.approx(200.0 / 3.0)

    def test_duplicate_eligible_sessions_counted_once_in_denominator(self) -> None:
        """Duplicate eligible-session ids (e.g. from an eval-time join) must not
        inflate the denominator; one reuse event over two unique sessions is 50%."""
        sessions = ["s1", "s1", "s2"]  # s1 duplicated
        events = [{"session_id": "s1", "rung": "incorporation"}]
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window={}
        )
        assert result["n_eligible_sessions"] == 2
        inc = result["rungs"]["incorporation"]
        assert inc["denominator"] == 2
        assert inc["numerator"] == 1
        assert inc["reuse_per_100_eligible"] == pytest.approx(50.0)

    def test_same_session_different_rungs_not_deduped(self) -> None:
        """One session appearing in two rungs counts independently per rung."""
        sessions = ["s1"]
        events = [
            {"session_id": "s1", "rung": "incorporation"},
            {"session_id": "s1", "rung": "influence"},
        ]
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window={}
        )
        assert result["rungs"]["incorporation"]["numerator"] == 1
        assert result["rungs"]["influence"]["numerator"] == 1

    def test_n_reuse_events_counts_raw_not_deduped(self) -> None:
        """The top-level n_reuse_events reflects raw event count, not deduped."""
        sessions = ["s1"]
        events = [
            {"session_id": "s1", "rung": "incorporation"},
            {"session_id": "s1", "rung": "incorporation"},
        ]
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window={}
        )
        assert result["n_reuse_events"] == 2


# ---------------------------------------------------------------------------
# Loader stub
# ---------------------------------------------------------------------------


class TestLoaderStub:
    """load_events_from_storage returns empty lists without error in P0."""

    def test_returns_empty_lists_no_db(self) -> None:
        sessions, events = load_events_from_storage()
        assert sessions == []
        assert events == []

    def test_returns_empty_lists_with_db_path(self, tmp_path) -> None:
        db = tmp_path / "pallium.db"
        sessions, events = load_events_from_storage(db, container_ref="c:test")
        assert sessions == []
        assert events == []

    def test_rollup_on_stub_output_is_safe(self) -> None:
        """Running the full pipeline with stub data must not raise."""
        sessions, events = load_events_from_storage()
        result = compute_reuse_rollup(
            sessions, events, eligibility_n=50, window={"note": "stub"}
        )
        for rung in result["rungs"].values():
            assert rung["reuse_per_100_eligible"] is None


# ---------------------------------------------------------------------------
# Visibility / governance violation reporting
# ---------------------------------------------------------------------------


class TestVisibilityViolationReporting:
    """The rollup output always carries a computed visibility-violation block."""

    def test_rollup_embeds_empty_report_by_default(self) -> None:
        result = compute_reuse_rollup([], [], eligibility_n=50, window={})
        vv = result["visibility_violations"]
        assert vv["violations"] == 0
        assert set(vv["by_type"]) == {"cross_container", "forgotten_exposed"}

    def test_rollup_embeds_supplied_report(self) -> None:
        report = {
            "violations": 0,
            "by_type": {"cross_container": 0, "forgotten_exposed": 0},
            "events_checked": 3,
            "exposed_ids_checked": 9,
        }
        result = compute_reuse_rollup(
            [], [], eligibility_n=50, window={}, visibility_report=report
        )
        assert result["visibility_violations"] is report

    def test_load_violations_empty_safe_no_db(self) -> None:
        from evals.historical_lookup_measurement import load_visibility_violations

        report = load_visibility_violations(None)
        assert report["violations"] == 0
        assert report["by_type"] == {"cross_container": 0, "forgotten_exposed": 0}

    def test_load_violations_clean_exposed_set_is_zero(self, tmp_path) -> None:
        """A clean exposed set (matching container, not forgotten) → 0 violations
        with a non-zero exposed_ids_checked (the count is computed, not assumed)."""
        import json

        from core.models import new_id, utc_now
        from evals.historical_lookup_measurement import load_visibility_violations
        from sqlalchemy import text
        from storage.sqlite import SQLiteStorageProvider

        db = tmp_path / "hist.db"
        storage = SQLiteStorageProvider(f"sqlite:///{db}")
        with storage._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO source_items (id, source_type, source_id, "
                    "content_type, content, container_ref, thread_ref, visibility, "
                    "processing_status, processing_attempts, created_at) VALUES "
                    "('s1','chat_message','ext-s1','text/plain','x','c:1','t:1',"
                    "'private','completed',0,'2026-08-01 00:00:01.000000')"
                )
            )
        storage.write_historical_lookup_event_row({
            "id": new_id(),
            "created_at": utc_now(),
            "event_type": "lookup",
            "session_id": "t:1",
            "container_ref": "c:1",
            "actor_ref": None,
            "trigger_origin": "agent_pull",
            "parent_lookup_id": None,
            "exposed_json": json.dumps([{"source_item_id": "s1", "raw_rank": 1, "score": 0.5}]),
            "visibility": "private",
        })
        report = load_visibility_violations(str(db), container_ref="c:1")
        assert report["violations"] == 0
        assert report["exposed_ids_checked"] == 1
        assert report["events_checked"] == 1

    def test_load_violations_detects_planted_cross_container(self, tmp_path) -> None:
        """A planted cross-container exposed id must be COUNTED (proves the
        field is computed, not hardcoded to 0)."""
        import json

        from core.models import new_id, utc_now
        from evals.historical_lookup_measurement import load_visibility_violations
        from sqlalchemy import text
        from storage.sqlite import SQLiteStorageProvider

        db = tmp_path / "hist.db"
        storage = SQLiteStorageProvider(f"sqlite:///{db}")
        with storage._engine.begin() as conn:
            # The exposed source item lives in a DIFFERENT container than the event.
            conn.execute(
                text(
                    "INSERT INTO source_items (id, source_type, source_id, "
                    "content_type, content, container_ref, thread_ref, visibility, "
                    "processing_status, processing_attempts, created_at) VALUES "
                    "('s-other','chat_message','ext','text/plain','x','c:OTHER','t:x',"
                    "'private','completed',0,'2026-08-01 00:00:01.000000')"
                )
            )
        storage.write_historical_lookup_event_row({
            "id": new_id(),
            "created_at": utc_now(),
            "event_type": "lookup",
            "session_id": "t:1",
            "container_ref": "c:1",
            "actor_ref": None,
            "trigger_origin": "agent_pull",
            "parent_lookup_id": None,
            "exposed_json": json.dumps([{"source_item_id": "s-other", "raw_rank": 1, "score": 0.5}]),
            "visibility": "private",
        })
        report = load_visibility_violations(str(db))
        assert report["by_type"]["cross_container"] == 1
        assert report["violations"] == 1


# ---------------------------------------------------------------------------
# Consensus rung — one vote per rater, robust to re-runs
# ---------------------------------------------------------------------------


class TestConsensusRungDedup:
    """A re-run appends a new label row per rater (labels are append-only). The
    consensus must count each rater ONCE, using that rater's LATEST label."""

    def _seed_event(self, storage):
        import json

        from core.models import utc_now

        storage.write_historical_lookup_event_row({
            "id": "ev-1",
            "created_at": utc_now(),
            "event_type": "lookup",
            "session_id": "t:1",
            "container_ref": "c:1",
            "actor_ref": None,
            "trigger_origin": "agent_pull",
            "parent_lookup_id": None,
            "exposed_json": json.dumps([{"source_item_id": "s1", "raw_rank": 1, "score": 0.5}]),
            "visibility": "private",
        })

    def _write_label(self, storage, *, rater_seed, rung, created):
        from datetime import datetime

        from core.models import new_id

        storage.write_historical_lookup_label_row({
            "id": new_id(),
            "lookup_event_id": "ev-1",
            "rater_seed": rater_seed,
            "rung": rung,
            "rationale": f"seed={rater_seed}",
            "created_at": datetime.fromisoformat(created),
        })

    def test_rerun_relabel_does_not_double_count(self, tmp_path) -> None:
        """One rater relabels on a re-run (incorporation → influence). With
        one-vote-per-rater dedup the latest label wins → influence. Double-
        counting would tie both rungs and fall back to incorporation."""
        import sqlite3

        from evals.historical_lookup_measurement import _consensus_rung
        from storage.sqlite import SQLiteStorageProvider

        db = tmp_path / "consensus.db"
        storage = SQLiteStorageProvider(f"sqlite:///{db}")
        self._seed_event(storage)
        # First run.
        self._write_label(storage, rater_seed="0", rung="incorporation",
                          created="2026-08-10 00:00:01.000000")
        # Re-run: same rater, changed verdict, later timestamp.
        self._write_label(storage, rater_seed="0", rung="influence",
                          created="2026-08-11 00:00:01.000000")

        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            assert _consensus_rung(conn, "ev-1") == "influence"
        finally:
            conn.close()

    def test_rerun_preserves_plurality_per_rater(self, tmp_path) -> None:
        """Three raters; one flips on a re-run. Latest-per-rater plurality:
        {0:influence, 1:incorporation, 2:influence} → influence. Counting every
        row (double-count) would make incorporation tie/win instead."""
        import sqlite3

        from evals.historical_lookup_measurement import _consensus_rung
        from storage.sqlite import SQLiteStorageProvider

        db = tmp_path / "consensus2.db"
        storage = SQLiteStorageProvider(f"sqlite:///{db}")
        self._seed_event(storage)
        # First run: two incorporation, one influence.
        self._write_label(storage, rater_seed="0", rung="incorporation",
                          created="2026-08-10 00:00:01.000000")
        self._write_label(storage, rater_seed="1", rung="incorporation",
                          created="2026-08-10 00:00:02.000000")
        self._write_label(storage, rater_seed="2", rung="influence",
                          created="2026-08-10 00:00:03.000000")
        # Re-run: rater 0 flips to influence with a later timestamp.
        self._write_label(storage, rater_seed="0", rung="influence",
                          created="2026-08-11 00:00:01.000000")

        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            assert _consensus_rung(conn, "ev-1") == "influence"
        finally:
            conn.close()
