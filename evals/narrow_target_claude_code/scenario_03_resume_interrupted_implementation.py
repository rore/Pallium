"""Scenario 3 — Resume an interrupted implementation correctly.

# measures: injection-precision

See docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md#scenario-3
"""

from __future__ import annotations

from ._shared import ScenarioResult, incomplete

SCENARIO_ID = "03-resume-interrupted-implementation"


def run() -> ScenarioResult:
    """task_checkpoint from Session A must surface at SessionStart in Session B.

    Placeholder: fixture wiring lands in Week 2.
    """
    return incomplete(
        SCENARIO_ID,
        reason="task_checkpoint fixture + branch/path-matched SessionStart replay not wired",
    )


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
