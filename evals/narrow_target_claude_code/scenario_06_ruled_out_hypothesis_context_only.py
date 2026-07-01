"""Scenario 6 — Ruled-out hypothesis stays context-only; new session's diagnosis stays free.

# measures: specificity

See docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md#scenario-6
"""

from __future__ import annotations

from ._shared import ScenarioResult, incomplete

SCENARIO_ID = "06-ruled-out-hypothesis-context-only"


def run() -> ScenarioResult:
    """Prior investigation named a ruled-out hypothesis. New session hits a
    superficially-similar error from a different cause. Pallium may surface
    the prior investigation as context (trigger-based), but must not inject
    it as the answer and must not preempt the agent's own diagnosis.

    Negative scenario — specificity contributor.

    Placeholder: fixture wiring lands in Week 2.
    """
    return incomplete(
        SCENARIO_ID,
        reason="ruled-out-hypothesis fixture + non-answer surfacing assertion not wired",
    )


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
