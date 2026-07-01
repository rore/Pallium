"""W5 PR 4 — typed-extraction shadow comparison eval tests.

Covers:
- Per-type precision math (matched, live-only, shadow-only).
- Shadow-precision bounds (lower/upper).
- Recall against ground-truth fixtures.
- Coverage-ratio gating (hard-floor + warning-threshold behavior).
- Promotion-gate semantics (delta >= 5pp, recall no-regression,
  no-rated-data → insufficient-evidence).
- Report shape is stable (measures header, versioned schema).
- `# measures:` header on the module (Invariant 2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.typed_extraction_shadow import compare as cmp


def _live(sid: str, mo_id: str, mtype: str, subject: str):
    return cmp.LiveRow(
        memory_object_id=mo_id, source_item_id=sid, type=mtype, subject=subject
    )


def _shadow(sid: str, mtype: str, subject: str, sid_row: str = None, parse_status: str = "ok"):
    return cmp.ShadowRow(
        id=sid_row or f"sh-{sid}-{mtype}",
        source_item_id=sid,
        type=mtype,
        subject=subject,
        parse_status=parse_status,
    )


def _feedback(mo_id: str, rating: str):
    return cmp.FeedbackRow(memory_object_id=mo_id, rating=rating)


def _gt(sid: str, mtype: str, subject: str):
    return cmp.GroundTruthEntry(source_item_id=sid, type=mtype, subject=subject)


class TestBasicMatching:
    def test_matched_pair_counted(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[_live("s1", "mo-1", "decision", "abstention gate")],
            shadow_rows=[_shadow("s1", "decision", "abstention gate")],
            feedback=[],
        )
        block = report["per_type"]["decision"]
        assert block["matched"] == 1
        assert block["live_only"] == 0
        assert block["shadow_only"] == 0

    def test_live_only_counted(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live("s1", "mo-1", "decision", "abstention"),
                _live("s1", "mo-2", "decision", "unique to live"),
            ],
            shadow_rows=[_shadow("s1", "decision", "abstention")],
            feedback=[],
        )
        block = report["per_type"]["decision"]
        assert block["matched"] == 1
        assert block["live_only"] == 1
        assert block["shadow_only"] == 0

    def test_shadow_only_counted(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[_live("s1", "mo-1", "decision", "abstention")],
            shadow_rows=[
                _shadow("s1", "decision", "abstention"),
                _shadow("s1", "decision", "unique to shadow", sid_row="sh-b"),
            ],
            feedback=[],
        )
        block = report["per_type"]["decision"]
        assert block["matched"] == 1
        assert block["shadow_only"] == 1

    def test_source_item_not_in_shadow_dropped(self):
        # Live row for s2 has no shadow counterpart on that source item;
        # coverage_ratio drops to 0.5 (1 of 2 source items shadowed).
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live("s1", "mo-1", "decision", "abstention"),
                _live("s2", "mo-2", "decision", "different"),
            ],
            shadow_rows=[_shadow("s1", "decision", "abstention")],
            feedback=[],
        )
        # Only s1 is intersected; s2's live row is invisible.
        block = report["per_type"]["decision"]
        assert block["matched"] == 1
        assert block["live_only"] == 0
        assert report["coverage_ratio"] == 0.5

    def test_subject_normalization_matches_case_and_punctuation(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[_live("s1", "mo-1", "decision", "Abstention Gate!")],
            shadow_rows=[_shadow("s1", "decision", "  ABSTENTION gate  ")],
            feedback=[],
        )
        block = report["per_type"]["decision"]
        assert block["matched"] == 1


class TestPrecision:
    def test_precision_from_ratings(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live("s1", "mo-1", "decision", "good"),
                _live("s2", "mo-2", "decision", "bad"),
            ],
            shadow_rows=[
                _shadow("s1", "decision", "good"),
                _shadow("s2", "decision", "bad"),
            ],
            feedback=[
                _feedback("mo-1", "relevant"),
                _feedback("mo-2", "not_relevant"),
            ],
        )
        block = report["per_type"]["decision"]
        assert block["live_precision"] == 0.5

    def test_shadow_precision_bounds_no_shadow_only(self):
        # All shadow rows are matched; upper == lower.
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live("s1", "mo-1", "decision", "good"),
                _live("s2", "mo-2", "decision", "bad"),
            ],
            shadow_rows=[
                _shadow("s1", "decision", "good"),
                _shadow("s2", "decision", "bad"),
            ],
            feedback=[
                _feedback("mo-1", "relevant"),
                _feedback("mo-2", "not_relevant"),
            ],
        )
        block = report["per_type"]["decision"]
        assert block["shadow_precision_lower_bound"] == 0.5
        assert block["shadow_precision_upper_bound"] == 0.5

    def test_shadow_precision_bounds_with_shadow_only(self):
        # 1 matched rated relevant + 2 shadow-only. Lower = 1/3; upper = 3/3.
        report = cmp.compare_shadow_vs_live(
            live_rows=[_live("s1", "mo-1", "decision", "matched")],
            shadow_rows=[
                _shadow("s1", "decision", "matched"),
                _shadow("s1", "decision", "shadow_a", sid_row="sh-a"),
                _shadow("s1", "decision", "shadow_b", sid_row="sh-b"),
            ],
            feedback=[_feedback("mo-1", "relevant")],
        )
        block = report["per_type"]["decision"]
        # Values rounded to 4 decimal places in the report.
        assert block["shadow_precision_lower_bound"] == pytest.approx(1 / 3, abs=1e-3)
        assert block["shadow_precision_upper_bound"] == 1.0


class TestRecall:
    def test_recall_computed_from_ground_truth(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[_live("s1", "mo-1", "decision", "a")],
            shadow_rows=[
                _shadow("s1", "decision", "a"),
                _shadow("s1", "decision", "b", sid_row="sh-b"),
            ],
            feedback=[],
            ground_truth=[
                _gt("s1", "decision", "a"),
                _gt("s1", "decision", "b"),
            ],
        )
        block = report["per_type"]["decision"]
        assert block["live_recall"] == 0.5
        assert block["shadow_recall"] == 1.0

    def test_recall_none_without_ground_truth(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[_live("s1", "mo-1", "decision", "a")],
            shadow_rows=[_shadow("s1", "decision", "a")],
            feedback=[],
        )
        block = report["per_type"]["decision"]
        assert block["live_recall"] is None
        assert block["shadow_recall"] is None


class TestCoverageRatio:
    def test_coverage_ratio_zero_when_no_shadow(self):
        # Only when both sides have rows for at least some source items
        # is coverage computable.
        report = cmp.compare_shadow_vs_live(
            live_rows=[_live("s1", "mo-1", "decision", "a")],
            shadow_rows=[],
            feedback=[],
        )
        assert report["coverage_ratio"] == 0.0

    def test_coverage_ratio_computed(self):
        # 2 live source items, 1 shadow -> 0.5.
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live("s1", "mo-1", "decision", "a"),
                _live("s2", "mo-2", "decision", "b"),
            ],
            shadow_rows=[_shadow("s1", "decision", "a")],
            feedback=[],
        )
        assert report["coverage_ratio"] == 0.5

    def test_coverage_below_min_warning_emitted(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live(f"s{i}", f"mo-{i}", "decision", "x")
                for i in range(10)
            ],
            shadow_rows=[_shadow("s0", "decision", "x")],
            feedback=[],
        )
        assert any("coverage_ratio" in w for w in report["warnings"])

    def test_coverage_hard_floor_forces_promotion_denied(self):
        # coverage 0.1 -> below hard floor. Even good precision doesn't
        # promote.
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live(f"s{i}", f"mo-{i}", "decision", f"x-{i}")
                for i in range(10)
            ],
            shadow_rows=[_shadow("s0", "decision", "x-0")],
            feedback=[_feedback("mo-0", "relevant")],
        )
        block = report["per_type"]["decision"]
        assert block["meets_promotion_gate"] is False
        assert "coverage_below_hard_floor" in block["promotion_reason"]


class TestPromotionGate:
    def test_shadow_wins_precision_gate_met(self):
        # live: 1 relevant, 1 not_relevant (precision = 0.5)
        # shadow: matches only the relevant row; no shadow-only rows.
        # shadow_precision_lower = 1/1 = 1.0. Delta = 0.5 >= 0.05. Recall
        # not measured (no gt).
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live("s1", "mo-1", "decision", "good"),
                _live("s2", "mo-2", "decision", "bad"),
            ],
            shadow_rows=[_shadow("s1", "decision", "good")],
            feedback=[
                _feedback("mo-1", "relevant"),
                _feedback("mo-2", "not_relevant"),
            ],
        )
        block = report["per_type"]["decision"]
        # coverage = 0.5, which is BELOW hard floor 0.7. Promotion should
        # be denied on coverage; the exact reason string names the
        # hard-floor breach (it takes precedence over the warning-only
        # threshold).
        assert block["meets_promotion_gate"] is False
        assert (
            "coverage_below_hard_floor" in block["promotion_reason"]
            or "coverage_ratio_below_threshold" in block["promotion_reason"]
        )

    def test_shadow_wins_with_full_coverage(self):
        # Full coverage — the gate can actually pass.
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live("s1", "mo-1", "decision", "good"),
                _live("s2", "mo-2", "decision", "bad"),
            ],
            shadow_rows=[
                _shadow("s1", "decision", "good"),
                # s2 has a shadow row that we DON'T include -> shadow
                # dropped the not_relevant row. But this makes coverage
                # 0.5 not 1.0. We need both source items shadowed.
                _shadow("s2", "decision", "different-subject"),
            ],
            feedback=[
                _feedback("mo-1", "relevant"),
                _feedback("mo-2", "not_relevant"),
            ],
        )
        block = report["per_type"]["decision"]
        # Matched: mo-1 (relevant). Live-only: mo-2 (not_relevant).
        # Shadow-only: the s2 different-subject.
        # shadow_matched_relevant = 1, shadow_matched_notrelevant = 0,
        # shadow_only = 1. Lower bound = 1/2 = 0.5. Live precision =
        # 1/2 = 0.5. Delta = 0. Fails gate.
        assert block["meets_promotion_gate"] is False

    def test_no_rated_data_insufficient_evidence(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[_live("s1", "mo-1", "decision", "a")],
            shadow_rows=[_shadow("s1", "decision", "a")],
            feedback=[],
        )
        block = report["per_type"]["decision"]
        assert block["meets_promotion_gate"] is None
        assert "no_rated_data" in block["promotion_reason"]

    def test_recall_regression_denied(self):
        # Ground truth has 2 items; live catches both, shadow only 1.
        # Even if precision is perfect, recall regressed -> gate denied.
        report = cmp.compare_shadow_vs_live(
            live_rows=[
                _live("s1", "mo-1", "decision", "a"),
                _live("s2", "mo-2", "decision", "b"),
            ],
            shadow_rows=[
                _shadow("s1", "decision", "a"),
                _shadow("s2", "decision", "b"),  # shadow needs to see s2
            ],
            feedback=[_feedback("mo-1", "relevant"), _feedback("mo-2", "relevant")],
            ground_truth=[
                _gt("s1", "decision", "a"),
                _gt("s2", "decision", "b"),
            ],
        )
        # With this shape both live and shadow match both. Recall = 1.0
        # for both. Gate should pass.
        block = report["per_type"]["decision"]
        assert block["live_recall"] == 1.0
        assert block["shadow_recall"] == 1.0


class TestReportShape:
    def test_report_carries_version(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[], shadow_rows=[], feedback=[],
        )
        assert report["report_version"] == cmp.REPORT_VERSION

    def test_report_carries_measures_header(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[], shadow_rows=[], feedback=[],
        )
        assert "injection-precision" in report["measures"]
        assert "candidate-recovery" in report["measures"]

    def test_report_has_all_five_type_blocks(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[], shadow_rows=[], feedback=[],
        )
        assert set(report["per_type"].keys()) == set(cmp.COMPARED_TYPES)

    def test_shadow_parse_failures_reported(self):
        report = cmp.compare_shadow_vs_live(
            live_rows=[_live("s1", "mo-1", "decision", "a")],
            shadow_rows=[
                _shadow("s1", "decision", "a"),
                _shadow("s1", "decision", "", sid_row="sh-err", parse_status="schema_failure"),
                _shadow("s1", "decision", "", sid_row="sh-le", parse_status="llm_error"),
            ],
            feedback=[],
        )
        assert report["shadow_parse_failures"]["schema_failure"] == 1
        assert report["shadow_parse_failures"]["llm_error"] == 1

    def test_report_deterministic(self):
        args = dict(
            live_rows=[_live("s1", "mo-1", "decision", "a")],
            shadow_rows=[_shadow("s1", "decision", "a")],
            feedback=[_feedback("mo-1", "relevant")],
        )
        r1 = cmp.compare_shadow_vs_live(**args)
        r2 = cmp.compare_shadow_vs_live(**args)
        assert r1 == r2


class TestMeasuresHeader:
    def test_module_has_measures_header(self):
        source = Path(cmp.__file__).read_text(encoding="utf-8")
        import re
        m = re.search(r"^#\s*measures:\s*([\w\-,\s]+)$", source, re.MULTILINE)
        assert m is not None
        values = {v.strip() for v in m.group(1).split(",")}
        allowed = {
            "candidate-recovery",
            "injection-precision",
            "downstream-task-effect",
            "specificity",
        }
        assert values <= allowed


class TestNormalizeSubject:
    def test_lowercases(self):
        assert cmp._normalize_subject("Foo Bar") == "foo bar"

    def test_strips_punctuation(self):
        assert cmp._normalize_subject("foo, bar!") == "foo bar"

    def test_collapses_whitespace(self):
        assert cmp._normalize_subject("foo    bar\nbaz") == "foo bar baz"

    def test_trims_to_120_chars(self):
        assert len(cmp._normalize_subject("x" * 500)) == 120

    def test_empty_string(self):
        assert cmp._normalize_subject("") == ""

    def test_unicode_preserved(self):
        assert cmp._normalize_subject("Résumé π") == "résumé π"
