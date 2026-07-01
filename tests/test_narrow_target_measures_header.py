"""W4 PR 4 — enforcement of the # measures: header on every scenario.

Invariant 2 (see docs/context/lessons.md and AGENTS.md): every
retrieval eval must state whether it measures candidate-recovery,
injection-precision, or downstream-task-effect. This lint fails loud
if a scenario module drops or corrupts its header.
"""

from __future__ import annotations

import pytest

from evals.narrow_target_claude_code import run_all
from evals.narrow_target_claude_code._shared import (
    assert_scenario_has_measures_header,
)


def test_run_all_module_has_measures_header():
    assert_scenario_has_measures_header(run_all)


@pytest.mark.parametrize("mod", run_all.SCENARIOS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_scenario_has_measures_header(mod):
    assert_scenario_has_measures_header(mod)


def test_all_scenarios_declared_in_run_all():
    """Regression: adding a new scenario file without registering it in
    run_all.SCENARIOS silently excludes it from the milestone replay.
    """
    from pathlib import Path

    scenarios_dir = Path(run_all.__file__).parent
    on_disk = sorted(
        p.stem for p in scenarios_dir.glob("scenario_*.py")
    )
    registered = sorted(m.__name__.rsplit(".", 1)[-1] for m in run_all.SCENARIOS)
    assert set(on_disk) == set(registered), (
        f"scenario file(s) missing from run_all.SCENARIOS: "
        f"on-disk={on_disk} registered={registered}"
    )
