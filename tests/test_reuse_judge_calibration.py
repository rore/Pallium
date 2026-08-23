"""Deterministic self-tests for reuse-judge calibration (no live LLM).

Covers the calibration deliverable end to end with a STUB judge:
- the committed gold fixture loads, is well-formed, spans all three rung
  categories, and is generic (no product names);
- judge-vs-gold Cohen's kappa is 1.0 → CALIBRATED when the judge agrees with
  the gold labels, and below threshold → UNCALIBRATED when it disagrees;
- run_judge surfaces the judge_vs_gold block in its serialised output;
- the rollup embeds a calibration block and stamps rung rates uncalibrated
  ONLY on an explicit calibrated=False, never changing the numerators.

The judge LLM is a deterministic in-process stub — no network calls.
"""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from evals.historical_lookup_judge import (
    GOLD_KAPPA_THRESHOLD,
    JUDGE_PROMPT_ID,
    JUDGE_PROMPT_VERSION,
    classification_metrics,
    run_judge,
)
from evals.historical_lookup_measurement import (
    _empty_calibration_report,
    compute_reuse_rollup,
)
from evals.reuse_judge_calibration import (
    DEFAULT_FIXTURE_PATH,
    _calibration_summary,
    build_reference_validation_summary,
    load_gold_fixture,
    main,
    run_reference_validation,
    seed_scratch_db,
)
from providers.llm.base import LLMJsonResponse


# ---------------------------------------------------------------------------
# Stub judge: verdict decided strictly by markers in the WORK AFTER block.
# ---------------------------------------------------------------------------
class _StubJudge:
    def generate_json(self, *, system_prompt, user_prompt, schema_description) -> LLMJsonResponse:
        work_after = user_prompt.split("WORK AFTER:", 1)[-1]
        if "INCORP_MARKER" in work_after:
            rung, genuine = "incorporation", True
        elif "INFLU_MARKER" in work_after:
            rung, genuine = "influence", True
        else:
            rung, genuine = "none", False
        payload = {
            "genuine_opportunity": genuine,
            "rung": rung,
            "evidence_span": "marker" if genuine else "",
            "direction": "agent_decided",
        }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


class _PartialFailingStub(_StubJudge):
    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        if "[reviewer pass #0]" in user_prompt:
            raise RuntimeError("simulated partial judge failure")
        return super().generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=schema_description,
        )


class _FailingStub(_StubJudge):
    """Like _StubJudge, but raises on any lookup whose prompt contains
    FAIL_MARKER — models an event where every judge call fails."""

    def generate_json(self, *, system_prompt, user_prompt, schema_description) -> LLMJsonResponse:
        if "FAIL_MARKER" in user_prompt:
            raise RuntimeError("simulated judge failure")
        return super().generate_json(
            system_prompt=system_prompt, user_prompt=user_prompt,
            schema_description=schema_description,
        )


def _inline_gold() -> list[dict]:
    """Six synthetic records — two per category — whose after_turns carry the
    stub markers, so the stub judge's verdict equals each record's gold_rung."""
    recs = []
    specs = [
        ("incorp-a", "incorporation", "did the thing. INCORP_MARKER"),
        ("incorp-b", "incorporation", "reused it. INCORP_MARKER"),
        ("influ-a", "influence", "shaped by it. INFLU_MARKER"),
        ("influ-b", "influence", "guided the work. INFLU_MARKER"),
        ("none-a", "none", "ignored history, wrote fresh."),
        ("none-b", "none", "nothing relevant surfaced."),
    ]
    for rid, rung, after in specs:
        recs.append({
            "id": rid,
            "container_ref": "git:example.com/acme-x",
            "before_turns": [{"role": "user", "content": "please help with the task"}],
            "retrieved_history": [] if rung == "none" else ["past decision text"],
            "after_turns": [{"role": "assistant", "content": after}],
            "gold_rung": rung,
        })
    return recs


# ---------------------------------------------------------------------------
# Committed gold fixture structure + genericness
# ---------------------------------------------------------------------------
class TestGoldFixture:
    def test_loads_and_well_formed(self) -> None:
        gold = load_gold_fixture(DEFAULT_FIXTURE_PATH)
        assert 10 <= len(gold) <= 20, "fixture should stay small but meaningful"
        rungs = {r["gold_rung"] for r in gold}
        assert rungs == {"incorporation", "influence", "none"}, "must span all 3 categories"
        for r in gold:
            assert r["before_turns"] and r["after_turns"], f"{r['id']}: turns present"

    def test_is_generic_no_product_names(self) -> None:
        raw = DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8").lower()
        banned = ["xlm", "pelican", "clmia", "sap-dev", "sap ", "atlas", "muxi", "pallium"]
        hits = [b for b in banned if b in raw]
        assert not hits, f"gold fixture must be generic; found banned tokens: {hits}"


# ---------------------------------------------------------------------------
# Judge-vs-gold agreement math + the calibrated verdict
# ---------------------------------------------------------------------------
class TestJudgeVsGold:
    def test_perfect_agreement_is_calibrated(self, tmp_path) -> None:
        db = tmp_path / "cal.db"
        gold_labels = seed_scratch_db(_inline_gold(), db)
        report = run_judge(
            db, provider=_StubJudge(), container_ref=None, eligibility_n=0,
            sample_size=500, seeds=[0, 1, 2], write_labels=False,
            gold_labels=gold_labels,
        )
        assert report.gold_kappa == pytest.approx(1.0)
        assert report.gold_kappa_n == 6
        assert report.calibrated is True

    def test_disagreement_is_uncalibrated(self, tmp_path) -> None:
        db = tmp_path / "cal.db"
        true_labels = seed_scratch_db(_inline_gold(), db)
        # Corrupt the gold labels so they systematically disagree with the
        # (marker-driven) judge verdicts → kappa below threshold.
        rotate = {"incorporation": "none", "influence": "incorporation", None: "influence"}
        wrong_labels = {ev: rotate[v] for ev, v in true_labels.items()}
        report = run_judge(
            db, provider=_StubJudge(), container_ref=None, eligibility_n=0,
            sample_size=500, seeds=[0, 1, 2], write_labels=False,
            gold_labels=wrong_labels,
        )
        assert report.gold_kappa is not None
        assert report.gold_kappa < GOLD_KAPPA_THRESHOLD
        assert report.calibrated is False

    def test_report_emits_judge_vs_gold_block(self, tmp_path) -> None:
        db = tmp_path / "cal.db"
        gold_labels = seed_scratch_db(_inline_gold(), db)
        report = run_judge(
            db, provider=_StubJudge(), container_ref=None, eligibility_n=0,
            sample_size=500, seeds=[0, 1, 2], write_labels=False,
            gold_labels=gold_labels,
        )
        block = report.to_dict()["judge_vs_gold"]
        assert set(block) >= {"kappa", "n", "threshold", "calibrated", "categories"}
        assert block["threshold"] == GOLD_KAPPA_THRESHOLD
        assert block["calibrated"] is True
        assert block["evidence_kind"] == "single_author_reference_set"
        assert block["confusion_matrix"]["incorporation"]["incorporation"] == 2
        assert block["per_class"]["influence"] == {
            "precision": 1.0, "recall": 1.0, "support": 2,
        }
        prompt = report.to_dict()["judge_prompt"]
        assert prompt == {"id": JUDGE_PROMPT_ID, "version": JUDGE_PROMPT_VERSION}

    def test_no_gold_labels_leaves_calibration_none(self, tmp_path) -> None:
        db = tmp_path / "cal.db"
        seed_scratch_db(_inline_gold(), db)
        report = run_judge(
            db, provider=_StubJudge(), container_ref=None, eligibility_n=0,
            sample_size=500, seeds=[0, 1, 2], write_labels=False,
        )
        assert report.gold_kappa is None
        assert report.calibrated is None

    def test_threshold_value(self) -> None:
        # Guards accidental drift of the documented calibration bar.
        assert GOLD_KAPPA_THRESHOLD == 0.7

    def test_all_failed_event_excluded_from_gold_vectors(self, tmp_path) -> None:
        # 6 clean records + 1 whose judge calls always fail (FAIL_MARKER). The
        # failing event must be dropped from the gold comparison, not folded in
        # as a "none" consensus (which would skew gold_kappa/gold_kappa_n).
        recs = _inline_gold()
        recs.append({
            "id": "fail-x",
            "container_ref": "git:example.com/acme-x",
            "before_turns": [{"role": "user", "content": "help please"}],
            "retrieved_history": ["some past decision"],
            "after_turns": [{"role": "assistant", "content": "attempted. FAIL_MARKER"}],
            "gold_rung": "incorporation",
        })
        db = tmp_path / "cal.db"
        gold_labels = seed_scratch_db(recs, db)
        report = run_judge(
            db, provider=_FailingStub(), container_ref=None, eligibility_n=0,
            sample_size=500, seeds=[0, 1, 2], write_labels=False,
            gold_labels=gold_labels,
        )
        # 7 gold events seeded, 1 all-failed → only 6 contribute to the vectors.
        assert report.gold_kappa_n == 6
        assert report.n_judge_failures == 3  # 3 seeds x 1 failing event
        # The 6 remaining agree perfectly with gold → still calibrated.
        assert report.gold_kappa == pytest.approx(1.0)
        assert report.calibrated is True


class TestReferenceValidation:
    def _report(self, tmp_path):
        db = tmp_path / "reference.db"
        labels = seed_scratch_db(_inline_gold(), db)
        return run_judge(
            db, provider=_StubJudge(), container_ref=None, eligibility_n=0,
            sample_size=500, seeds=[0, 1, 2], write_labels=False,
            gold_labels=labels,
        )

    def test_zero_denominator_metrics_are_explicit(self) -> None:
        metrics = classification_metrics(["none"], ["none"])
        assert metrics["per_class"]["incorporation"] == {
            "precision": 0.0, "recall": 0.0, "support": 0,
        }

    def test_two_identical_groups_pass(self, tmp_path) -> None:
        report = self._report(tmp_path)
        event_ids = list(report.consensus_rung)
        summary = build_reference_validation_summary(
            report, report, event_ids=event_ids, fixture_path="inline"
        )
        assert summary["reference_set_passed"] is True
        assert summary["mutual_agreement"]["kappa"] == pytest.approx(1.0)
        assert summary["mutual_agreement"]["n"] == len(event_ids)
        assert summary["judge_vs_gold"]["kappa"] == pytest.approx(1.0)
        assert summary["judge_vs_gold"]["n"] == len(event_ids)

    def test_extra_event_fails(self, tmp_path) -> None:
        report = self._report(tmp_path)
        report.consensus_rung["ev:extra"] = None
        event_ids = [event_id for event_id in report.consensus_rung if event_id != "ev:extra"]
        summary = build_reference_validation_summary(
            report, report, event_ids=event_ids, fixture_path="inline"
        )
        assert summary["reference_set_passed"] is False
        assert summary["mutual_agreement"]["extra_events"]["a"] == ["ev:extra"]

    def test_legacy_fields_use_minimum_group_values(self, tmp_path) -> None:
        group_a = self._report(tmp_path)
        group_b = deepcopy(group_a)
        group_b.gold_kappa = 0.8
        group_b.gold_kappa_n = 5
        summary = build_reference_validation_summary(
            group_a,
            group_b,
            event_ids=list(group_a.consensus_rung),
            fixture_path="inline",
        )
        assert summary["judge_vs_gold"]["kappa"] == pytest.approx(0.8)
        assert summary["judge_vs_gold"]["n"] == 5
        assert summary["reference_set_passed"] is False

    def test_missing_event_fails(self, tmp_path) -> None:
        report = self._report(tmp_path)
        event_ids = [*report.consensus_rung, "ev:missing"]
        summary = build_reference_validation_summary(
            report, report, event_ids=event_ids, fixture_path="inline"
        )
        assert summary["reference_set_passed"] is False
        assert summary["mutual_agreement"]["missing_events"]["a"] == ["ev:missing"]

    @pytest.mark.parametrize("sample_size", [6, 500])
    def test_exact_and_over_count_full_lifecycle(self, tmp_path, sample_size) -> None:
        fixture = tmp_path / "reference.json"
        fixture.write_text(json.dumps({"lookups": _inline_gold()}), encoding="utf-8")
        summary = run_reference_validation(
            provider=_StubJudge(),
            fixture_path=fixture,
            seed_groups=((0, 1, 2), (3, 4, 5)),
            sample_size=sample_size,
        )
        assert summary["reference_set_passed"] is True
        assert summary["mutual_agreement"]["n"] == 6

    def test_invalid_reference_label_is_rejected(self, tmp_path) -> None:
        fixture = tmp_path / "invalid.json"
        records = _inline_gold()
        records[0]["gold_rung"] = "maybe"
        fixture.write_text(json.dumps({"lookups": records}), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid gold_rung"):
            load_gold_fixture(fixture)

    def test_partial_seed_failure_is_visible_and_rejected(self, tmp_path) -> None:
        fixture = tmp_path / "partial.json"
        fixture.write_text(json.dumps({"lookups": _inline_gold()}), encoding="utf-8")
        summary = run_reference_validation(
            provider=_PartialFailingStub(), fixture_path=fixture
        )
        assert summary["reference_set_passed"] is False
        assert len(summary["mutual_agreement"]["failed_events"]["a"]) == 6
        assert summary["mutual_agreement"]["failed_events"]["b"] == []

    def test_all_failed_groups_do_not_pass(self, tmp_path) -> None:
        fixture = tmp_path / "failed.json"
        records = _inline_gold()
        for record in records:
            record["after_turns"][0]["content"] = "FAIL_MARKER"
        fixture.write_text(json.dumps({"lookups": records}), encoding="utf-8")
        summary = run_reference_validation(
            provider=_FailingStub(), fixture_path=fixture
        )
        assert summary["reference_set_passed"] is False
        assert len(summary["mutual_agreement"]["failed_events"]["a"]) == 6
        assert summary["mutual_agreement"]["n"] == 0

    @pytest.mark.parametrize(
        "seed_groups",
        [((0, 1, 2),), ((0, 1, 2), (3, 4, 5), (6, 7, 8))],
    )
    def test_exactly_two_seed_groups_are_required(self, seed_groups) -> None:
        with pytest.raises(ValueError, match="exactly two"):
            run_reference_validation(provider=_StubJudge(), seed_groups=seed_groups)

    def test_underpowered_seed_group_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least three"):
            run_reference_validation(
                provider=_StubJudge(), seed_groups=((0, 1), (2, 3, 4))
            )

    def test_duplicate_seed_within_group_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="distinct"):
            run_reference_validation(
                provider=_StubJudge(), seed_groups=((0, 0, 1), (2, 3, 4))
            )

    def test_overlapping_seed_groups_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="disjoint"):
            run_reference_validation(
                provider=_StubJudge(), seed_groups=((0, 1, 2), (2, 3, 4))
            )

    def test_dry_run_cli_serializes_failed_reference_check(self, tmp_path) -> None:
        output = tmp_path / "report.json"
        assert main([
            "--dry-run", "--sample-size", "0", "--output", str(output),
        ]) == 0
        summary = json.loads(output.read_text(encoding="utf-8"))
        assert summary["reference_set_passed"] is False
        assert summary["mutual_agreement"]["n"] == 0
        assert summary["judge_prompt"]["version"] == JUDGE_PROMPT_VERSION


# ---------------------------------------------------------------------------
# Rollup calibration flag — presentation only, never touches numerators
# ---------------------------------------------------------------------------
class TestRollupCalibration:
    _sessions = ["s0", "s1", "s2", "s3"]
    _events = [
        {"session_id": "s0", "rung": "incorporation"},
        {"session_id": "s1", "rung": "influence"},
    ]

    def _rollup(self, calibration=None):
        return compute_reuse_rollup(
            self._sessions, self._events, eligibility_n=0,
            window={"note": "test"}, calibration=calibration,
        )

    def test_default_is_empty_safe(self) -> None:
        out = self._rollup()
        assert out["calibration"] == _empty_calibration_report()
        assert out["calibration"]["calibrated"] is None
        for rung in out["rungs"].values():
            assert "calibrated" not in rung  # unknown, not stamped

    def test_uncalibrated_stamps_every_rung(self) -> None:
        baseline = self._rollup()
        out = self._rollup(calibration={"kappa": 0.2, "calibrated": False})
        assert out["calibration"]["calibrated"] is False
        for key, rung in out["rungs"].items():
            assert rung["calibrated"] is False
            # numerator/denominator/Wilson identical to the no-calibration call
            assert rung["numerator"] == baseline["rungs"][key]["numerator"]
            assert rung["denominator"] == baseline["rungs"][key]["denominator"]
            assert rung["wilson_95"] == baseline["rungs"][key]["wilson_95"]

    def test_calibrated_true_does_not_stamp(self) -> None:
        out = self._rollup(calibration={"kappa": 0.8, "calibrated": True})
        assert out["calibration"]["calibrated"] is True
        for rung in out["rungs"].values():
            assert "calibrated" not in rung  # calibrated → no uncalibrated stamp

    def test_stamps_from_runner_actual_serialized_output(self, tmp_path) -> None:
        # Regression for the shape mismatch: the calibration RUNNER nests the
        # verdict under judge_vs_gold, so the rollup must stamp rungs when passed
        # that ACTUAL serialized summary — not only a hand-built flat block.
        db = tmp_path / "cal.db"
        true_labels = seed_scratch_db(_inline_gold(), db)
        rotate = {"incorporation": "none", "influence": "incorporation", None: "influence"}
        wrong_labels = {ev: rotate[v] for ev, v in true_labels.items()}
        report = run_judge(
            db, provider=_StubJudge(), container_ref=None, eligibility_n=0,
            sample_size=500, seeds=[0, 1, 2], write_labels=False,
            gold_labels=wrong_labels,
        )
        summary = _calibration_summary(report, fixture_path="inline")
        # Sanity: this is the nested shape the runner writes to disk.
        assert summary["judge_vs_gold"]["calibrated"] is False
        assert "calibrated" not in summary  # not flat

        out = self._rollup(calibration=summary)
        for rung in out["rungs"].values():
            assert rung["calibrated"] is False  # stamped despite nested shape

    def test_nested_calibrated_true_does_not_stamp(self) -> None:
        out = self._rollup(calibration={"judge_vs_gold": {"calibrated": True}})
        for rung in out["rungs"].values():
            assert "calibrated" not in rung
