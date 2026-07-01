"""Shared runner shape for narrow-target scenarios.

Each scenario module exposes a `run()` function returning a dict with the
canonical fields. Runners are deterministic: same inputs → same output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Verdict = Literal["PASS", "FAIL", "INCOMPLETE"]


@dataclass
class ScenarioResult:
    """Canonical result shape for a narrow-target scenario replay.

    Fields track the measurements the milestone spec requires:
    injection-precision and specificity (not candidate-recovery).
    """

    scenario_id: str
    verdict: Verdict
    precision: float  # correct-injection / total-injection on trigger turn(s); NaN if N/A
    specificity: float  # correct-non-injection / non-injection opportunities; NaN if N/A
    timing: str  # "on_time" | "late" | "early" | "n/a"
    type_distribution: dict[str, int] = field(default_factory=dict)
    diagnostic: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def incomplete(scenario_id: str, reason: str) -> ScenarioResult:
    """Standard INCOMPLETE result used until fixtures are wired."""
    return ScenarioResult(
        scenario_id=scenario_id,
        verdict="INCOMPLETE",
        precision=float("nan"),
        specificity=float("nan"),
        timing="n/a",
        type_distribution={},
        diagnostic=f"fixture not wired yet: {reason}",
    )
