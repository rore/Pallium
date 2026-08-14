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

import pytest

from evals.historical_lookup_judge import GOLD_KAPPA_THRESHOLD, run_judge
from evals.historical_lookup_measurement import (
    _empty_calibration_report,
    compute_reuse_rollup,
)
from evals.reuse_judge_calibration import (
    DEFAULT_FIXTURE_PATH,
    load_gold_fixture,
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
        assert GOLD_KAPPA_THRESHOLD == 0.6


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
