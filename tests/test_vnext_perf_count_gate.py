"""Default-lane count-regression gate for the vNext retrieval hot paths.

The deterministic per-path DB round-trip COUNTS (not latency) are the committed,
gated perf signal for the shared retrieval chokepoint. The full harness guard
(``tests/test_vnext_perf_harness.py``) is ``slow``-marked and runs in no default
CI lane, so a count regression on the shared path would not auto-fail default CI.

This test IS in the default lane (not ``slow``): it runs the full-mode
count-compare against the committed baseline (``evals/vnext_perf_baseline.json``)
and fails on regression. It skips the advisory latency loops
(``include_latency=False``) so the gate pays only for the deterministic counts.

Latency/benchmark measurement stays advisory-only and ``slow``.
"""

from __future__ import annotations

import json

from evals import vnext_perf_harness as h


def test_count_compare_matches_committed_baseline() -> None:
    """Full-mode per-path DB round-trip counts stay within tolerance of the
    committed baseline. This is the deterministic regression gate."""
    assert h.BASELINE_PATH.exists(), (
        f"missing committed baseline at {h.BASELINE_PATH}; "
        "regenerate with `python -m evals.vnext_perf_harness --baseline`"
    )
    report = h.run_measurements(include_latency=False)
    # The gate skips advisory latency; it must not compute it.
    assert "latency_advisory" not in report
    baseline = json.loads(h.BASELINE_PATH.read_text(encoding="utf-8"))
    problems = h.compare_to_baseline(report, baseline)
    assert problems == [], "count regression(s) vs committed baseline:\n" + "\n".join(problems)


def test_compare_detects_a_seeded_regression() -> None:
    """The gate actually gates: a baseline perturbed to expect FEWER queries
    than measured must be reported as a regression (proves the comparison is
    load-bearing, not vacuously passing). The committed baseline file is never
    modified — the perturbation is an in-memory copy."""
    report = h.run_measurements(include_latency=False)
    baseline = json.loads(h.BASELINE_PATH.read_text(encoding="utf-8"))
    assert report["counts"]["source_only_query"]["results"] > 0, (
        "seeded source-only measurement must return a real corpus hit before count comparison"
    )
    # Drop the source_only_query expected count to 1 so the larger measured
    # count reads as a regression regardless of tolerance.
    baseline["counts"]["source_only_query"]["engine_queries"] = 1
    problems = h.compare_to_baseline(report, baseline)
    assert any("source_only_query" in p for p in problems)
