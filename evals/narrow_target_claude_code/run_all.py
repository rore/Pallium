"""Run all narrow-target scenarios and write aggregate baseline JSON.

# measures: injection-precision, specificity

Measures: injection-precision + specificity (not candidate-recovery).

Usage:
    python -m evals.narrow_target_claude_code.run_all \
        --output evals/narrow_target_claude_code/baseline_2026-07-01.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from . import (
    scenario_01_repeat_failed_command,
    scenario_02_recall_python_on_windows_constraint,
    scenario_03_resume_interrupted_implementation,
    scenario_04_surface_prior_investigation_on_error,
    scenario_05_preserve_architectural_decision,
    scenario_06_ruled_out_hypothesis_context_only,
    scenario_07_unrelated_prior_errors_no_injection,
    scenario_negative_no_operational_fact,
)
from ._shared import ScenarioResult, assert_scenario_has_measures_header

SCENARIOS = (
    scenario_01_repeat_failed_command,
    scenario_02_recall_python_on_windows_constraint,
    scenario_03_resume_interrupted_implementation,
    scenario_04_surface_prior_investigation_on_error,
    scenario_05_preserve_architectural_decision,
    scenario_06_ruled_out_hypothesis_context_only,
    scenario_07_unrelated_prior_errors_no_injection,
    scenario_negative_no_operational_fact,
)


def _lint_scenario_headers() -> None:
    """Enforce the # measures: header on every scenario module + this
    runner. Fails fast on the runner side so a missing header trips
    before scenarios execute.
    """
    from . import run_all as _self

    assert_scenario_has_measures_header(_self)
    for mod in SCENARIOS:
        assert_scenario_has_measures_header(mod)


def _mean(xs: list[float]) -> float:
    """Mean, ignoring NaN. Returns NaN if all inputs are NaN."""
    valid = [x for x in xs if not math.isnan(x)]
    if not valid:
        return float("nan")
    return sum(valid) / len(valid)


def _aggregate(results: list[ScenarioResult]) -> dict:
    verdicts = [r.verdict for r in results]
    proactive_total = sum(r.proactive_operational_fact_count for r in results)
    return {
        "meta": {
            "measures": "injection-precision, specificity",
            "not_measures": "candidate-recovery, downstream-task-effect",
            "scenario_count": len(results),
        },
        "verdicts": {
            "PASS": verdicts.count("PASS"),
            "FAIL": verdicts.count("FAIL"),
            "INCOMPLETE": verdicts.count("INCOMPLETE"),
        },
        "precision_mean": _mean([r.precision for r in results]),
        "specificity_mean": _mean([r.specificity for r in results]),
        # W4 acceptance: aggregate must be zero.
        "proactive_operational_fact_count": proactive_total,
        "scenarios": [r.to_dict() for r in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write aggregate JSON to this path. If omitted, print to stdout.",
    )
    args = parser.parse_args(argv)

    # Enforce the measures-header lint before running any scenario.
    _lint_scenario_headers()

    results: list[ScenarioResult] = []
    for mod in SCENARIOS:
        try:
            results.append(mod.run())
        except Exception as exc:  # noqa: BLE001 -- eval runner must not crash on one scenario
            from ._shared import incomplete
            results.append(
                incomplete(
                    getattr(mod, "SCENARIO_ID", mod.__name__),
                    reason=f"runner exception: {exc!r}",
                )
            )

    report = _aggregate(results)

    payload = json.dumps(report, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")

    # Exit non-zero if any scenario FAILed OR the zero-proactive
    # invariant tripped. INCOMPLETE is not a failure.
    any_failed = report["verdicts"]["FAIL"] > 0
    proactive_violation = report["proactive_operational_fact_count"] > 0
    return 1 if (any_failed or proactive_violation) else 0


if __name__ == "__main__":
    raise SystemExit(main())
